import pandas as pd
from sqlalchemy import text
from src.database import SessionLocal, engine


def process_and_load_csv(file_path):
    """
    接收文件路径，执行清洗、分表并入库
    """
    try:
        # 1. 加载全量数据 (10,000条)
        df = pd.read_csv(file_path)

        # 2. 核心字段校验
        required_cols = ['user_id', 'item_id', 'purchase_intent', 'interaction_rate']
        if not all(col in df.columns for col in required_cols):
            return False, "核心字段缺失，请检查CSV格式。"

        # 3. 维度表1：dim_user (去重并提取静态属性)
        # 包含：user_id, age, gender, user_level, register_days, total_spend, purchase_freq 等
        user_cols = ['user_id', 'age', 'gender', 'user_level', 'register_days',
                     'total_spend', 'purchase_freq', 'follow_num', 'fans_num']
        dim_user_df = df[user_cols].drop_duplicates(subset=['user_id'])

        # 4. 维度表2：dim_item (去重并提取商品属性)
        # 包含：item_id, category, price, discount_rate, has_video 等
        item_cols = ['item_id', 'category', 'price', 'discount_rate',
                     'title_length', 'title_emo_score', 'img_count', 'has_video']
        dim_item_df = df[item_cols].drop_duplicates(subset=['item_id'])

        # 5. 事实表：fact_user_behavior (动态交互数据)
        # 包含：pv_count, add2cart, collect_num, interaction_rate, purchase_intent, label 等
        behavior_cols = ['user_id', 'item_id', 'pv_count', 'add2cart', 'collect_num',
                         'like_num', 'comment_num', 'share_num', 'coupon_received',
                         'coupon_used', 'interaction_rate', 'purchase_intent',
                         'last_click_gap', 'label']
        fact_behavior_df = df[behavior_cols]

        with engine.begin() as conn:
            # --- 新增步骤：先清理旧数据，防止主键冲突 ---
            # 注意顺序：由于有外键约束，必须先删事实表，再删维度表
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
            conn.execute(text("TRUNCATE TABLE fact_user_behavior;"))
            conn.execute(text("TRUNCATE TABLE usr_persona;"))
            conn.execute(text("TRUNCATE TABLE dim_user;"))
            conn.execute(text("TRUNCATE TABLE dim_item;"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))

            # --- 执行写入 ---
            dim_user_df.to_sql('dim_user', con=conn, if_exists='append', index=False)
            dim_item_df.to_sql('dim_item', con=conn, if_exists='append', index=False)
            fact_behavior_df.to_sql('fact_user_behavior', con=conn, if_exists='append', index=False)

        return True, f"成功刷新数据库！已处理 {len(fact_behavior_df)} 条记录。"

    except Exception as e:
        return False, f"入库异常: {str(e)}"