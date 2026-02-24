import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from src.database import engine
from sqlalchemy import text
import joblib
import os
import numpy as np
import gc
from concurrent.futures import ProcessPoolExecutor

# 全局共享变量，减少子进程序列化开销
_shared_data = {}


def _init_worker(behavior_summary, user_cat_affinity, all_items_prepped, feature_names):
    """
    子进程初始化：加载预处理好的特征数据
    """
    global _shared_data
    _shared_data['behavior_summary'] = behavior_summary
    _shared_data['user_cat_affinity'] = user_cat_affinity
    _shared_data['all_items_prepped'] = all_items_prepped
    _shared_data['feature_names'] = feature_names
    # 预加载模型到内存
    _shared_data['model'] = joblib.load('libs/rf_model.pkl')


def _predict_user_batch_extreme_precision(user_batch, top_n=5, threshold=0.6):
    """
    高性能预测函数：剔除重复的独热编码逻辑
    """
    global _shared_data
    try:
        rf = _shared_data['model']
        # all_items_prepped 已经是包含 dummy 变量的完整商品表
        all_items = _shared_data['all_items_prepped']
        behavior_summary = _shared_data['behavior_summary']
        user_cat_affinity = _shared_data['user_cat_affinity']
        feature_names = _shared_data['feature_names']

        # 1. 构造候选集 (笛卡尔积) - 优化点：利用预编码数据
        combined = user_batch.assign(key=1).merge(all_items.assign(key=1), on='key').drop('key', axis=1)

        # 2. 快速合并交互特征与偏好特征
        combined = combined.merge(behavior_summary, on=['user_id', 'item_id'], how='left')
        combined = combined.merge(user_cat_affinity, on=['user_id', 'category'], how='left')

        # 3. 快速填充缺失值
        fill_cols = ['pv_count', 'add2cart', 'collect_num', 'like_num', 'cat_pref_score']
        combined[fill_cols] = combined[fill_cols].fillna(0)

        # 4. 特征对齐：补全模型需要的列
        for col in feature_names:
            if col not in combined.columns:
                combined[col] = 0

        # 5. 矩阵化预测
        X_pred = combined[list(feature_names)]
        combined['score'] = rf.predict_proba(X_pred)[:, 1]

        # 6. 精准过滤与动态截断
        result = combined[combined['score'] >= threshold]
        result = result.sort_values(['user_id', 'score'], ascending=[True, False]).groupby('user_id').head(top_n).copy()

        # 保底逻辑
        if result.empty:
            result = combined.sort_values(['user_id', 'score'], ascending=[True, False]).groupby('user_id').head(
                1).copy()

        result['model_type'] = 'RF-Optimized'
        result['rank'] = result.groupby('user_id').cumcount() + 1

        del combined, X_pred
        gc.collect()
        return result[['user_id', 'item_id', 'score', 'model_type', 'category', 'rank']]
    except Exception as e:
        print(f"子进程预测报错: {e}")
        return pd.DataFrame()


def train_recommendation_model(top_n=5, threshold=0.6):
    """
    优化后的主训练与并行预测流程
    """
    try:
        print("\n" + "========================================")
        print("🚀 RF-Optimized 高性能精准模式启动")
        print("⚙️  资源限制: 4 核心并行 (CPU-Bound Optimization)")
        print(f"📏 策略参数：阈值({threshold}) | Top-{top_n}")
        print("========================================")

        # 1. 训练数据加载
        query = """
                SELECT b.user_id, b.item_id, b.label, i.category,
                       COALESCE(b.pv_count, 0) as pv_count, COALESCE(b.add2cart, 0) as add2cart, 
                       COALESCE(b.collect_num, 0) as collect_num, COALESCE(b.like_num, 0) as like_num,
                       p.cluster_label, p.is_churn_risk, i.price, i.discount_rate, i.has_video
                FROM fact_user_behavior b
                JOIN usr_persona p ON b.user_id = p.user_id
                JOIN dim_item i ON b.item_id = i.item_id
                """
        df = pd.read_sql(query, engine)

        # 计算类目偏好特征
        user_cat_affinity = df.groupby(['user_id', 'category']).agg(cat_pref_score=('pv_count', 'sum')).reset_index()
        df = df.merge(user_cat_affinity, on=['user_id', 'category'], how='left')

        # 2. 训练逻辑：正则化处理
        print(">>> 正在拟合随机森林模型 (n_estimators=150, max_depth=15)...")
        X_train = pd.get_dummies(df.drop(['label', 'user_id', 'item_id'], axis=1), columns=['category'])
        rf = RandomForestClassifier(
            n_estimators=150, max_depth=15, min_samples_leaf=10,
            class_weight='balanced', n_jobs=-1, random_state=42
        )
        rf.fit(X_train, df['label'])

        if not os.path.exists('libs'): os.makedirs('libs')
        joblib.dump(rf, 'libs/rf_model.pkl')
        feature_names = rf.feature_names_in_

        # 3. 【核心优化点】：在主进程预先处理商品特征编码
        all_users = pd.read_sql("SELECT user_id, cluster_label, is_churn_risk FROM usr_persona", engine)
        all_items = pd.read_sql("SELECT item_id, price, discount_rate, has_video, category FROM dim_item", engine)

        # 预先生成独热编码，避免子进程重复计算
        dummies = pd.get_dummies(all_items['category'], prefix='category')
        all_items_prepped = pd.concat([all_items, dummies], axis=1)

        behavior_summary = df[['user_id', 'item_id', 'pv_count', 'add2cart', 'collect_num', 'like_num']]
        active_users = all_users[all_users['user_id'].isin(df['user_id'].unique())]

        # 任务分片
        user_chunks = np.array_split(active_users, 20)
        predictions = []

        print(f">>> 开始并行预测，分片数: 20")
        num_chunks = len(user_chunks)
        with ProcessPoolExecutor(
                max_workers=4,
                initializer=_init_worker,
                initargs=(behavior_summary, user_cat_affinity, all_items_prepped, feature_names)
        ) as executor:
            futures = [executor.submit(_predict_user_batch_extreme_precision, chunk, top_n, threshold) for chunk in
                       user_chunks]
            for i, f in enumerate(futures):
                res = f.result()
                if not res.empty: predictions.extend(res.to_dict(orient='records'))
                progress = (i + 1) / num_chunks * 100
                print(f"📊 预测进度: {progress:.0f}%")

        # 4. 优化后的数据库写入
        if predictions:
            res_df = pd.DataFrame(predictions)
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM recommendation_results WHERE model_type = 'RF-Optimized'"))
                # 使用 method='multi' 大幅提升插入速度
                res_df.to_sql(
                    'recommendation_results',
                    con=conn,
                    if_exists='append',
                    index=False,
                    method='multi',
                    chunksize=2000
                )

        print(f"✅ 执行完毕。Threshold {threshold}, Top-{top_n}, 共生成 {len(predictions)} 条数据。")
        return True, "Success"
    except Exception as e:
        print(f"❌ 运行异常: {e}")
        return False, str(e)


def get_top_recommendations(user_id, top_n=5):
    """查询接口"""
    try:
        db_query = text(
            "SELECT item_id, category, score FROM recommendation_results WHERE user_id = :uid AND model_type = 'RF-Optimized' ORDER BY `rank` ASC LIMIT :limit")
        results = pd.read_sql(db_query, engine, params={"uid": str(user_id), "limit": top_n})
        return results.to_dict(orient='records') if not results.empty else []
    except:
        return []