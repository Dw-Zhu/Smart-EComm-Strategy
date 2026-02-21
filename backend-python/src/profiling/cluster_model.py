import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from src.database import engine
from sqlalchemy import text


def train_user_clusters(n_clusters=4):
    """
    全量画像构建：补齐社交、消费、偏好及敏感度维度
    """
    try:
        # 1. 多表联查：提取原始特征
        query = """
                SELECT u.*, \
                       b.interaction_rate, \
                       b.purchase_intent, \
                       b.last_click_gap, \
                       i.category, \
                       i.price         as item_price, \
                       i.discount_rate as item_discount
                FROM dim_user u
                         JOIN fact_user_behavior b ON u.user_id = b.user_id
                         JOIN dim_item i ON b.item_id = i.item_id \
                """
        raw_df = pd.read_sql(query, engine)
        if raw_df.empty:
            return False, "数据库为空，请先入库数据。"

        # 2. 按用户维度进行特征聚合
        user_groups = raw_df.groupby('user_id')
        df = user_groups.agg({
            'total_spend': 'first',
            'purchase_freq': 'first',
            'register_days': 'first',
            'fans_num': 'first',
            'follow_num': 'first',
            'interaction_rate': 'mean',
            'purchase_intent': 'mean',
            'last_click_gap': 'max',
            'item_discount': 'mean'
        }).reset_index()

        # 3. 计算业务指标
        # 社交影响力
        df['social_influence'] = (df['fans_num'] * 0.7 + df['follow_num'] * 0.3).clip(0, 100)

        # --- 方案3：基于 K-Means 的动态消费等级划分 ---
        # 提取消费总额进行一维聚类
        spend_data = df[['total_spend']].values
        # 即使整体聚类是4类，消费等级我们通常还是划分为3类（低/中/高）
        spend_kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
        df['spend_cluster'] = spend_kmeans.fit_predict(spend_data)

        # 【重要】重排序：确保聚类中心均值小的标记为"低消费"，大的为"高消费"
        # 否则 KMeans 随机生成的 0,1,2 标签并不代表金额大小
        centers = df.groupby('spend_cluster')['total_spend'].mean().sort_values().index
        spend_mapping = {centers[0]: "低消费", centers[1]: "中消费", centers[2]: "高消费"}
        df['consumption_level'] = df['spend_cluster'].map(spend_mapping)
        # ------------------------------------------

        # 核心偏好品类
        pref_cat = raw_df.groupby(['user_id', 'category']).size().reset_index(name='cnt')
        df['preferred_category'] = pref_cat.sort_values('cnt', ascending=False).groupby('user_id')[
            'category'].first().values
        # 价格敏感度
        df['price_sensitivity'] = df['item_discount'] * 10.0
        # 忠诚度评分
        df['loyalty_score'] = (df['register_days'] * 0.3 + df['interaction_rate'] * 0.7).clip(0, 100)
        # 流失风险判定
        df['is_churn_risk'] = (df['last_click_gap'] > 30).astype(int)
        # 活跃度标签
        df['activity_level'] = df['interaction_rate'].apply(lambda x: "活跃" if x > 10 else "沉睡")

        # 4. 执行多维度综合 K-means 聚类（用于生成最终画像标签）
        scaler = StandardScaler()
        cluster_feats = ['total_spend', 'purchase_freq', 'interaction_rate', 'purchase_intent']
        scaled = scaler.fit_transform(df[cluster_feats])
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        df['cluster_label'] = kmeans.fit_predict(scaled)

        # 5. 定义画像标签映射
        tag_map = {0: "潜力新客", 1: "高价值核心", 2: "流失风险", 3: "低频长尾"}
        df['persona_tag'] = df['cluster_label'].map(tag_map)

        # 6. 回写至 usr_persona 表
        with engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
            conn.execute(text("TRUNCATE TABLE usr_persona;"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))

            # 严格对应 SQL 表字段名
            write_df = df[[
                'user_id', 'cluster_label', 'persona_tag', 'social_influence',
                'consumption_level', 'preferred_category', 'activity_level',
                'price_sensitivity', 'loyalty_score', 'is_churn_risk'
            ]].copy()

            write_df.to_sql('usr_persona', con=conn, if_exists='append', index=False)

        return True, "深度画像构建完成，所有字段已补齐。"

    except Exception as e:
        return False, f"画像构建异常: {str(e)}"