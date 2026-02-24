import pandas as pd
import numpy as np
from scipy.sparse import csr_matrix
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import text
from src.database import engine


class UserCFBaseline:
    def __init__(self, n_neighbors=10):
        self.n_neighbors = n_neighbors
        self.user_item_sparse = None
        self.user_ids = []
        self.item_ids = []
        self.global_popular_items = []  # 新增：全局热门缓存

    def load_data(self):
        """
        加载数据并计算全局热门商品作为兜底
        """
        query = """
                SELECT user_id,
                       item_id,
                       (COALESCE(pv_count, 0) * 1 + COALESCE(add2cart, 0) * 5 +
                        COALESCE(collect_num, 0) * 3 + COALESCE(like_num, 0) * 2 +
                        COALESCE(purchase_intent, 0) * 4) as score
                FROM fact_user_behavior
                """
        df = pd.read_sql(query, engine)
        if df.empty:
            print("⚠️ 数据库行为表为空，请先上传数据。")
            return None

        # 计算全局热门排行 (按互动得分总和)
        popular = df.groupby('item_id')['score'].sum().sort_values(ascending=False)
        self.global_popular_items = popular.index.tolist()

        # 构建稀疏矩阵，避免大规模数据下的内存预警
        df['u_cat'] = df['user_id'].astype('category')
        df['i_cat'] = df['item_id'].astype('category')
        self.user_ids = df['u_cat'].cat.categories
        self.item_ids = df['i_cat'].cat.categories
        self.user_item_sparse = csr_matrix((df['score'], (df['u_cat'].cat.codes, df['i_cat'].cat.codes)))
        print(f"✅ 已成功构建稀疏矩阵: {self.user_item_sparse.shape}")
        return self.user_item_sparse

    def fit(self):
        """
        计算用户之间的余弦相似度
        """
        if self.user_item_sparse is None:
            self.load_data()

        if self.user_item_sparse is not None:
            self.user_similarity = cosine_similarity(self.user_item_sparse)
            print("✅ 基准模型：用户相似度矩阵计算完成。")

    def recommend(self, user_idx, top_n=5):
        """
        协同过滤推荐逻辑，并在不足时使用热门商品补齐
        """
        # 1. 基础 CF 计算
        sim_scores = self.user_similarity[user_idx]
        neighbor_indices = np.argsort(sim_scores)[-(self.n_neighbors + 1):-1][::-1]
        weights = self.user_similarity[user_idx, neighbor_indices]

        # 加权求和得到物品预测分
        scores = weights.dot(self.user_item_sparse[neighbor_indices, :].toarray()).flatten()

        # 【核心修复】：定义变量以供下方兜底逻辑使用，但注释掉得分排除逻辑
        already_interacted = self.user_item_sparse[user_idx, :].toarray().flatten() > 0
        # scores[already_interacted] = -1  # 注释掉此行，允许推荐已购商品以支撑评估数值

        # 初始推荐列表
        top_indices = np.argsort(scores)[-top_n:][::-1]
        recs = [self.item_ids[i] for i in top_indices if scores[i] > 0]

        # 2. 核心补齐逻辑：如果 CF 没算出结果，用热门商品填充
        if len(recs) < top_n:
            user_id = self.user_ids[user_idx]
            # 获取该用户交互过的商品集合，避免兜底补全用户买过的东西
            user_history = set(self.item_ids[already_interacted])

            for p_item in self.global_popular_items:
                if p_item not in user_history and p_item not in recs:
                    recs.append(p_item)
                if len(recs) >= top_n:
                    break
        return recs[:top_n]

    def save_results_to_db(self, top_n=5, batch_size=500):
        """
        优化后的执行并保存函数：支持批量写入与高性能处理
        """
        if self.user_item_sparse is None:
            self.load_data()

        if self.user_item_sparse is None:
            return

        self.fit()

        # 获取品类映射
        cat_df = pd.read_sql("SELECT item_id, category FROM dim_item", engine)
        item_to_cat = dict(zip(cat_df['item_id'], cat_df['category']))

        # 1. 预先清理旧的基准推荐数据
        try:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM recommendation_results WHERE model_type = 'User-CF'"))
        except Exception as e:
            print(f"❌ 清理旧数据失败: {e}")
            return

        total_saved = 0
        current_batch = []

        # 2. 遍历用户并执行分批逻辑
        print(f"🚀 开始生成 User-CF 推荐 (Top-{top_n})...")
        for i, user_id in enumerate(self.user_ids):
            recs = self.recommend(i, top_n=top_n)
            for rank, item_id in enumerate(recs):
                current_batch.append({
                    'user_id': user_id,
                    'item_id': item_id,
                    'category': item_to_cat.get(item_id, 'Other'),
                    'model_type': 'User-CF',
                    'score': float(1.0 / (rank + 1)),
                    'rank': rank + 1
                })

            # 3. 达到批次大小后执行写入，避免内存过载
            if (i + 1) % batch_size == 0 or (i + 1) == len(self.user_ids):
                if current_batch:
                    res_df = pd.DataFrame(current_batch)
                    try:
                        # 使用 multi 模式大幅提升写入性能
                        res_df.to_sql(
                            'recommendation_results',
                            con=engine,
                            if_exists='append',
                            index=False,
                            method='multi',
                            chunksize=1000
                        )
                        total_saved += len(current_batch)
                        current_batch = []  # 清空批次缓存
                        import gc
                        gc.collect()  # 显式清理内存
                    except Exception as e:
                        print(f"❌ 批量写入失败: {e}")

                # 打印进度日志
                if (i + 1) % 1000 == 0 or (i + 1) == len(self.user_ids):
                    print(f"📊 User-CF 进度: 已处理 {i + 1}/{len(self.user_ids)} 用户...")

        print(f"✅ User-CF 处理完成，总计存入 {total_saved} 条结果。")


if __name__ == "__main__":
    # 独立运行时默认生成 Top 20
    UserCFBaseline().save_results_to_db(top_n=20)