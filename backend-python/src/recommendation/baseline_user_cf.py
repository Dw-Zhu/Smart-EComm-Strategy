import pandas as pd
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import text
from src.database import engine  # 确保你项目中 src/database.py 已配置好


class UserCFBaseline:
    def __init__(self, n_neighbors=10):
        self.n_neighbors = n_neighbors
        self.user_item_matrix = None
        self.user_similarity = None
        self.user_mapping = {}
        self.item_mapping = {}

    def load_data(self):
        """
        根据 SQL 结构加载交互数据。
        整合浏览、加购、收藏、点赞等行为作为综合评分。
        """
        # 基于 fact_user_behavior 的字段计算综合得分
        query = """
                SELECT user_id, \
                       item_id,
                       (pv_count * 0.1 + add2cart * 0.3 + collect_num * 0.2 +
                        like_num * 0.2 + purchase_intent * 0.2) as rating
                FROM fact_user_behavior \
                """
        df = pd.read_sql(query, engine)

        if df.empty:
            print("⚠️ 数据库行为表为空，请先检查数据导入情况。")
            return None

        # 构建用户-物品评分矩阵
        self.user_item_matrix = df.pivot_table(index='user_id', columns='item_id', values='rating').fillna(0)

        # 记录映射关系，处理 varchar(50) 类型的 ID
        self.user_mapping = {i: user_id for i, user_id in enumerate(self.user_item_matrix.index)}
        self.item_mapping = {i: item_id for i, item_id in enumerate(self.user_item_matrix.columns)}

        return self.user_item_matrix

    def fit(self):
        """
        计算用户之间的余弦相似度。
        """
        if self.user_item_matrix is None:
            self.load_data()

        if self.user_item_matrix is not None:
            self.user_similarity = cosine_similarity(self.user_item_matrix)
            print("✅ 相似度矩阵计算完成。")

    def recommend(self, user_id, top_n=10):
        """
        执行 Top-N 推荐逻辑。
        """
        if user_id not in self.user_item_matrix.index:
            return []

        user_idx = list(self.user_item_matrix.index).index(user_id)
        similarities = self.user_similarity[user_idx]

        # 找到最相似的邻居
        similar_users_idx = np.argsort(similarities)[-(self.n_neighbors + 1):-1][::-1]

        user_ratings = self.user_item_matrix.values
        predicted_ratings = np.zeros(user_ratings.shape[1])

        for idx in similar_users_idx:
            sim_score = similarities[idx]
            predicted_ratings += sim_score * user_ratings[idx]

        # 排除已交互过的商品
        already_interacted = np.where(user_ratings[user_idx] > 0)[0]
        predicted_ratings[already_interacted] = -1

        recommended_indices = np.argsort(predicted_ratings)[-top_n:][::-1]

        return [self.item_mapping[idx] for idx in recommended_indices if predicted_ratings[idx] > 0]

    def save_results_to_db(self, top_n=10):
        """
        将推荐结果批量存入 recommendation_results 表。
        """
        if self.user_similarity is None:
            self.fit()

        all_recs = []
        user_ids = self.user_item_matrix.index

        print(f"开始处理 {len(user_ids)} 个用户的推荐数据...")

        for user_id in user_ids:
            recs = self.recommend(user_id, top_n=top_n)
            for rank, item_id in enumerate(recs):
                all_recs.append({
                    'user_id': user_id,
                    'item_id': item_id,
                    'model_type': 'User-CF',
                    'score': float(1.0 / (rank + 1)),
                    'rank': rank + 1
                })

        if all_recs:
            recs_df = pd.DataFrame(all_recs)
            with engine.begin() as conn:
                # 清理旧数据，确保 model_type 区分
                conn.execute(text("DELETE FROM recommendation_results WHERE model_type = 'User-CF'"))
                # 写入结果
                recs_df.to_sql('recommendation_results', con=conn, if_exists='append', index=False)
            print(f"✅ 成功入库 {len(all_recs)} 条 User-CF 推荐结果。")


if __name__ == "__main__":
    cf_baseline = UserCFBaseline()
    cf_baseline.save_results_to_db()