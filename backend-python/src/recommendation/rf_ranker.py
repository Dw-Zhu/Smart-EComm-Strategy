import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from src.database import engine
from sqlalchemy import text
import joblib
import os
import numpy as np
import gc
from concurrent.futures import ProcessPoolExecutor


def _predict_user_batch(user_batch, all_items, feature_names):
    """
    子进程执行函数：超小规模批处理以保护内存
    """
    try:
        import joblib
        import gc
        if not isinstance(user_batch, pd.DataFrame):
            user_batch = pd.DataFrame(user_batch)

        model_path = 'libs/rf_model.pkl'
        if not os.path.exists(model_path):
            return pd.DataFrame()

        rf = joblib.load(model_path)

        # 批量处理：避免一次性生成过大的笛卡尔积表
        combined = user_batch.assign(key=1).merge(all_items.assign(key=1), on='key').drop('key', axis=1)
        combined_encoded = pd.get_dummies(combined, columns=['category'])

        for col in feature_names:
            if col not in combined_encoded.columns:
                combined_encoded[col] = 0

        X_pred = combined_encoded[list(feature_names)]
        combined['score'] = rf.predict_proba(X_pred)[:, 1]

        # 筛选结果并立即释放临时大表
        result = combined.sort_values(['user_id', 'score'], ascending=[True, False]).groupby('user_id').head(10)

        del combined, combined_encoded, X_pred
        gc.collect()  # 强制清理子进程内存

        return result
    except Exception as e:
        print(f"子进程异常: {str(e)}")
        return pd.DataFrame()


def train_recommendation_model():
    """
    保守型训练引擎：限制 CPU 和内存占用
    """
    try:
        print("\n" + "=" * 30)
        print("启动保守型模型训练任务 (限制核心数)...")

        query = "SELECT b.label, p.cluster_label, p.is_churn_risk, i.price, i.discount_rate, i.has_video, i.category FROM fact_user_behavior b JOIN usr_persona p ON b.user_id = p.user_id JOIN dim_item i ON b.item_id = i.item_id"
        df = pd.read_sql(query, engine)

        if df.empty:
            return False, "数据不足，无法训练。"

        # 训练阶段也限制并行度
        rf = RandomForestClassifier(n_estimators=30, n_jobs=2, max_depth=8, random_state=42)
        rf.fit(pd.get_dummies(df.drop('label', axis=1), columns=['category']), df['label'])

        if not os.path.exists('libs'): os.makedirs('libs')
        joblib.dump(rf, 'libs/rf_model.pkl')

        # 预测阶段：保守的进程分配
        all_users = pd.read_sql("SELECT user_id, cluster_label, is_churn_risk FROM usr_persona", engine)
        all_items = pd.read_sql("SELECT item_id, price, discount_rate, has_video, category FROM dim_item", engine)
        feature_names = rf.feature_names_in_

        # 策略：只开启 2 个并行进程，且分片更细
        num_workers = 2
        indices = np.array_split(range(len(all_users)), 20)  # 分成 20 份小块排队
        user_chunks = [all_users.iloc[idx] for idx in indices]

        predictions_to_save = []

        print(f"模式：低功耗并行。核心数: {num_workers}, 任务分片: 20")

        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(_predict_user_batch, chunk, all_items, feature_names) for chunk in user_chunks]
            for i, future in enumerate(futures):
                res_df = future.result()
                if not res_df.empty:
                    predictions_to_save.extend(
                        res_df[['user_id', 'item_id', 'category', 'score']].to_dict(orient='records'))
                    print(f"进度：已平稳完成 {i + 1}/20...")
                gc.collect()  # 主进程也进行内存清理

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM recommendation_results"))
            insert_sql = text(
                "INSERT INTO recommendation_results (user_id, item_id, category, score) VALUES (:user_id, :item_id, :category, :score)")
            conn.execute(insert_sql, predictions_to_save)

        return True, f"平稳训练完成，生成 {len(predictions_to_save)} 条策略"
    except Exception as e:
        return False, str(e)



def get_top_recommendations(user_id, top_n=5):
    """
    实时预测：优先读取持久化数据，保证响应速度
    """
    try:
        db_query = f"SELECT item_id, category, score FROM recommendation_results WHERE user_id = '{user_id}' ORDER BY score DESC LIMIT {top_n}"
        results = pd.read_sql(db_query, engine)

        if not results.empty:
            return results.to_dict(orient='records')

        # 保底逻辑：若无持久化数据则进行实时计算
        model_path = 'libs/rf_model.pkl'
        if not os.path.exists(model_path): return []
        rf = joblib.load(model_path)

        user_df = pd.read_sql(f"SELECT cluster_label, is_churn_risk FROM usr_persona WHERE user_id = '{user_id}'",
                              engine)
        if user_df.empty: return []

        items_df = pd.read_sql("SELECT item_id, price, discount_rate, has_video, category FROM dim_item", engine)
        predict_df = items_df.copy()
        predict_df['cluster_label'] = user_df['cluster_label'].values[0]
        predict_df['is_churn_risk'] = user_df['is_churn_risk'].values[0]

        predict_df_encoded = pd.get_dummies(predict_df, columns=['category'])
        for col in rf.feature_names_in_:
            if col not in predict_df_encoded.columns: predict_df_encoded[col] = 0

        X_predict = predict_df_encoded[rf.feature_names_in_]
        items_df['score'] = rf.predict_proba(X_predict)[:, 1]

        top_items = items_df.sort_values(by='score', ascending=False).head(top_n)
        return top_items[['item_id', 'category', 'score']].to_dict(orient='records')

    except Exception as e:
        print(f"推荐预测异常: {str(e)}")
        return []