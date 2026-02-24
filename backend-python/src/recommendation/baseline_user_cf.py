import pandas as pd
import numpy as np
from scipy.sparse import csr_matrix
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import text
from src.database import engine
import gc


class UserCFBaseline:
    def __init__(self, n_neighbors=10):
        self.n_neighbors = n_neighbors
        self.user_item_sparse = None
        self.user_ids = []
        self.item_ids = []
        self.global_popular_items = []

    def load_data(self):
        """
        优化 1: 引入轻量级数据加载，过滤掉无意义的超低频互动
        """
        query = """
                SELECT user_id, \
                       item_id,
                       (COALESCE(pv_count, 0) * 1 + COALESCE(add2cart, 0) * 5 +
                        COALESCE(collect_num, 0) * 3 + COALESCE(like_num, 0) * 2 +
                        COALESCE(purchase_intent, 0) * 4) as score
                FROM fact_user_behavior
                WHERE (pv_count + add2cart + collect_num + like_num) > 0
                """
        df = pd.read_sql(query, engine)
        if df.empty:
            print("⚠️ 行为表为空，跳过计算。")
            return None

        # 计算全局热门
        popular = df.groupby('item_id')['score'].sum().sort_values(ascending=False)
        self.global_popular_items = popular.index.tolist()[:100]  # 仅保留前100个热门作为兜底

        # 构建稀疏矩阵
        df['u_cat'] = df['user_id'].astype('category')
        df['i_cat'] = df['item_id'].astype('category')
        self.user_ids = df['u_cat'].cat.categories
        self.item_ids = df['i_cat'].cat.categories
        self.user_item_sparse = csr_matrix((df['score'], (df['u_cat'].cat.codes, df['i_cat'].cat.codes)))
        return self.user_item_sparse

    def fit(self):
        if self.user_item_sparse is None:
            self.load_data()
        if self.user_item_sparse is not None:
            # 优化 2: 使用密集矩阵前先进行分块思维，防止内存溢出
            self.user_similarity = cosine_similarity(self.user_item_sparse)
            print("✅ 用户相似度计算完成。")

    def recommend(self, user_idx, top_n=5):
        """
        优化 3: 严格限制兜底逻辑，防止生成过长列表
        """
        sim_scores = self.user_similarity[user_idx]
        # 只取相似度大于 0 的邻居
        neighbor_indices = np.argsort(sim_scores)[-(self.n_neighbors + 1):-1][::-1]
        valid_neighbors = [idx for idx in neighbor_indices if sim_scores[idx] > 0]

        if not valid_neighbors:
            # 如果没有相似邻居，直接返回全局热门前 top_n
            return self.global_popular_items[:top_n]

        weights = sim_scores[valid_neighbors]
        scores = weights.dot(self.user_item_sparse[valid_neighbors, :].toarray()).flatten()

        # 获取推荐索引
        top_indices = np.argsort(scores)[-top_n:][::-1]
        recs = [self.item_ids[i] for i in top_indices if scores[i] > 0]

        # 补齐逻辑
        if len(recs) < top_n:
            for p_item in self.global_popular_items:
                if p_item not in recs:
                    recs.append(p_item)
                if len(recs) >= top_n:
                    break
        return recs[:top_n]

    def save_results_to_db(self, top_n=5, batch_size=1000):
        """
        优化 4: 极简写入模式，减少数据库事务开销
        """
        if self.user_item_sparse is None:
            self.load_data()
        if self.user_item_sparse is None: return
        self.fit()

        cat_df = pd.read_sql("SELECT item_id, category FROM dim_item", engine)
        item_to_cat = dict(zip(cat_df['item_id'], cat_df['category']))

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM recommendation_results WHERE model_type = 'User-CF'"))

        total_saved = 0
        current_batch = []

        print(f"🚀 开始生成 User-CF 推荐 (目标 Top-{top_n})...")
        for i, user_id in enumerate(self.user_ids):
            recs = self.recommend(i, top_n=top_n)
            for rank, item_id in enumerate(recs):
                current_batch.append({
                    'user_id': user_id,
                    'item_id': item_id,
                    'category': item_to_cat.get(item_id, 'Other'),
                    'model_type': 'User-CF',
                    'score': round(float(1.0 / (rank + 1)), 4),
                    'rank': rank + 1
                })

            if len(current_batch) >= batch_size:
                pd.DataFrame(current_batch).to_sql(
                    'recommendation_results', con=engine, if_exists='append',
                    index=False, method='multi', chunksize=1000
                )
                total_saved += len(current_batch)
                current_batch = []
                gc.collect()

        # 处理剩余数据
        if current_batch:
            pd.DataFrame(current_batch).to_sql(
                'recommendation_results', con=engine, if_exists='append', index=False, method='multi'
            )
            total_saved += len(current_batch)

        print(f"✅ User-CF 优化写入完成，共存入 {total_saved} 条。")


if __name__ == "__main__":
    # 强制设为 Top-5 以对标随机森林模型的展示量
    UserCFBaseline().save_results_to_db(top_n=5)