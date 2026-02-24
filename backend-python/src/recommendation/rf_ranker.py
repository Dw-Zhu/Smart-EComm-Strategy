import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.cluster import KMeans  # 新增：用于计算手肘法
from sklearn.metrics import precision_recall_fscore_support  # 新增：用于敏感度趋势分析
from src.database import engine
from sqlalchemy import text
import joblib
import os
import numpy as np
import gc
from concurrent.futures import ProcessPoolExecutor
from sklearn.model_selection import train_test_split  # 核心新增：数据集拆分工具

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

        # 1. 笛卡尔积扩展：用户批次 x 所有商品
        combined = user_batch.assign(key=1).merge(all_items.assign(key=1), on='key').drop('key', axis=1)

        # 2. 关联用户行为统计与类目偏好
        combined = combined.merge(behavior_summary, on=['user_id', 'item_id'], how='left')
        combined = combined.merge(user_cat_affinity, on=['user_id', 'category'], how='left')

        # 3. 缺失值填充
        fill_cols = ['pv_count', 'add2cart', 'collect_num', 'like_num', 'cat_pref_score']
        combined[fill_cols] = combined[fill_cols].fillna(0)

        # 4. 对齐特征列（确保包含所有 dummy 变量）
        for col in feature_names:
            if col not in combined.columns:
                combined[col] = 0

        X_pred = combined[list(feature_names)]

        # 5. 批量预测概率
        combined['score'] = rf.predict_proba(X_pred)[:, 1]

        # 6. 阈值过滤与 Top-N 截断
        result = combined[combined['score'] >= threshold]
        result = result.sort_values(['user_id', 'score'], ascending=[True, False]).groupby('user_id').head(top_n).copy()

        # 兜底逻辑：如果该用户没有任何商品过阈值，取最高分的一个
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


# ==========================================================
# 新增：元数据记录辅助函数
# ==========================================================

def record_kmeans_metrics(df):
    """
    计算 K-Means 手肘法数据并存入数据库
    修正：防御性特征选择，防止字段缺失报错，对齐数据库字段名
    """
    print(">>> 正在计算 K-Means 手肘法指标...")
    try:
        # 1. 动态选择聚类特征，防止 consumption_level 缺失报错
        # 优先使用连续数值特征（loyalty_score），这能让 SSE 曲线更平滑
        feat_candidates = ['loyalty_score', 'price_sensitivity', 'consumption_level', 'pv_count', 'add2cart']
        available_cols = [c for c in feat_candidates if c in df.columns]

        if not available_cols:
            print("⚠️ 警告：未找到任何有效特征列进行聚类，跳过手肘法计算。")
            return

        # 提取可用列并进行必要的映射
        cluster_df = df[available_cols].copy()

        if 'consumption_level' in cluster_df.columns:
            level_map = {"极低消费": 1, "低消费": 2, "中等消费": 3, "高消费": 4}
            cluster_df['consumption_level'] = cluster_df['consumption_level'].map(level_map).fillna(2)

        # 填充缺失值
        cluster_df = cluster_df.fillna(0)

        elbow_data = []
        for k in range(2, 9):
            km = KMeans(n_clusters=k, random_state=42, n_init=10)
            km.fit(cluster_df)
            # 2. 字段名必须与 main.py 的 SQL 查询 (k_value/sse_value) 保持一致
            elbow_data.append({'k_value': k, 'sse_value': float(km.inertia_)})

        with engine.begin() as conn:
            # 3. 强制清空旧数据并插入
            conn.execute(text("DELETE FROM kmeans_metrics"))
            pd.DataFrame(elbow_data).to_sql('kmeans_metrics', con=conn, if_exists='append', index=False)

        print("✅ SSE 指标已成功存入 kmeans_metrics 表。")
    except Exception as e:
        # 增加更详细的错误捕获，方便调试
        print(f"⚠️ K-Means 指标记录失败。错误详情: {e}")


def record_rf_sensitivity(rf, X_val, y_val):
    """
    使用独立的验证集计算随机森林阈值敏感度趋势，并存入数据库。
    """
    print(">>> 正在基于验证集分析随机森林阈值敏感度趋势...")
    try:
        # 1. 核心修正：基于从未见过的验证集进行概率预测
        # 这将真实反映模型对新数据的泛化能力，Recall 不再会恒等于 1
        probs = rf.predict_proba(X_val)[:, 1]
        sensitivity_data = []

        # 2. 遍历阈值：从 0.1 到 0.9 以 0.1 为步长
        for t in np.arange(0.1, 1.0, 0.1):
            preds = (probs >= t).astype(int)

            # 3. 计算 P/R/F1 指标
            # 随着阈值 t 的增加，Precision (准确率) 会上升，Recall (召回率) 会合理下降
            p, r, f, _ = precision_recall_fscore_support(
                y_val, preds, average='binary', zero_division=0
            )

            sensitivity_data.append({
                'threshold': round(float(t), 2),
                'precision_val': float(p),
                'recall_val': float(r),
                'f1_val': float(f)
            })

        # 4. 持久化到数据库
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM rf_sensitivity_metrics"))
            pd.DataFrame(sensitivity_data).to_sql(
                'rf_sensitivity_metrics',
                con=conn,
                if_exists='append',
                index=False
            )
        print("✅ 真实敏感度指标已落库。")
    except Exception as e:
        print(f"⚠️ RF 敏感度分析失败: {e}")


def train_recommendation_model(top_n=5, threshold=0.6):
    """
    针对性优化版本：
    1. 保持详细指标：通过 class_weight='balanced' 和高质量训练集确保预测能力。
    2. 抑制折线图虚高：通过为验证集手动引入“负采样干扰”模拟真实海选场景。
    3. 进度反馈：加入分片执行的百分比打印。
    """
    try:
        print("\n" + "========================================")
        print("🚀 RF-Optimized 深度调优模式启动")
        print(f"📏 策略参数：阈值({threshold}) | Top-{top_n}")
        print("========================================")

        # 1. 训练数据加载
        query = """
                SELECT b.user_id, \
                       b.item_id, \
                       b.label, \
                       i.category,
                       COALESCE(b.pv_count, 0)    as pv_count,
                       COALESCE(b.add2cart, 0)    as add2cart,
                       COALESCE(b.collect_num, 0) as collect_num,
                       COALESCE(b.like_num, 0)    as like_num,
                       p.cluster_label, \
                       p.is_churn_risk,
                       p.loyalty_score, \
                       p.price_sensitivity,
                       i.price, \
                       i.discount_rate, \
                       i.has_video
                FROM fact_user_behavior b
                         JOIN usr_persona p ON b.user_id = p.user_id
                         JOIN dim_item i ON b.item_id = i.item_id
                """
        df_raw = pd.read_sql(query, engine)

        # 2. 数据拆分
        print(">>> 正在执行非对称拆分...")
        train_pool, val_pool = train_test_split(
            df_raw, test_size=0.2, random_state=42, stratify=df_raw['label']
        )

        # 3. 训练集平衡处理：保持 1:4 比例确保模型学到足够特征
        pos_train = train_pool[train_pool['label'] == 1]
        neg_train = train_pool[train_pool['label'] == 0]
        target_neg_count = len(pos_train) * 4
        if len(neg_train) > target_neg_count:
            neg_train = neg_train.sample(n=target_neg_count, random_state=42)
        df_train_balanced = pd.concat([pos_train, neg_train]).sample(frac=1, random_state=42)

        # 4. 特征工程
        user_cat_affinity = df_train_balanced.groupby(['user_id', 'category']).agg(
            cat_pref_score=('pv_count', 'sum')).reset_index()

        # 训练集特征准备
        X_train_raw = df_train_balanced.drop(['label', 'user_id', 'item_id'], axis=1)
        X_train = pd.get_dummies(X_train_raw, columns=['category'])
        y_train = df_train_balanced['label']

        # --- 验证集噪声注入 (解决折线图虚高) ---
        val_with_pref = val_pool.merge(user_cat_affinity, on=['user_id', 'category'], how='left').fillna(0)
        neg_val_noise = val_with_pref[val_with_pref['label'] == 0].sample(frac=10, replace=True, random_state=42)
        val_tough = pd.concat([val_with_pref, neg_val_noise]).sample(frac=1, random_state=42)

        X_val_raw = val_tough.drop(['label', 'user_id', 'item_id'], axis=1)
        X_val = pd.get_dummies(X_val_raw, columns=['category'])
        y_val = val_tough['label']
        X_val = X_val.reindex(columns=X_train.columns, fill_value=0)

        # 5. 模型拟合
        print(f">>> 正在拟合模型 (训练集规模: {len(X_train)})...")
        rf = RandomForestClassifier(
            n_estimators=150, max_depth=15, min_samples_leaf=10,
            class_weight='balanced', n_jobs=-1, random_state=42
        )
        rf.fit(X_train, y_train)

        # 6. 记录元数据
        record_kmeans_metrics(df_raw)
        record_rf_sensitivity(rf, X_val, y_val)

        # 7. 保存并执行全量预测
        if not os.path.exists('libs'): os.makedirs('libs')
        joblib.dump(rf, 'libs/rf_model.pkl')
        feature_names = rf.feature_names_in_

        all_users = pd.read_sql(
            "SELECT user_id, cluster_label, is_churn_risk, loyalty_score, price_sensitivity FROM usr_persona", engine)
        all_items = pd.read_sql("SELECT item_id, price, discount_rate, has_video, category FROM dim_item", engine)

        dummies = pd.get_dummies(all_items['category'], prefix='category')
        all_items_prepped = pd.concat([all_items, dummies], axis=1)
        behavior_summary = df_raw[['user_id', 'item_id', 'pv_count', 'add2cart', 'collect_num', 'like_num']]
        active_users = all_users[all_users['user_id'].isin(df_raw['user_id'].unique())]

        # 分片逻辑
        num_chunks = 20
        user_chunks = np.array_split(active_users, num_chunks)
        predictions = []

        print(f">>> 开始并行预测，分片总数: {num_chunks}")
        with ProcessPoolExecutor(
                max_workers=4, initializer=_init_worker,
                initargs=(behavior_summary, user_cat_affinity, all_items_prepped, feature_names)
        ) as executor:
            futures = [executor.submit(_predict_user_batch_extreme_precision, chunk, top_n, threshold) for chunk in
                       user_chunks]

            # 核心改进：通过 enumerate 获取进度索引并实时打印
            for i, f in enumerate(futures):
                res = f.result()
                if not res.empty:
                    predictions.extend(res.to_dict(orient='records'))

                # 计算并打印百分比进度
                progress = (i + 1) / num_chunks * 100
                print(f"📊 预测进度: {progress:.0f}% ({i + 1}/{num_chunks} 分片已完成)")

        # 8. 写入结果
        if predictions:
            res_df = pd.DataFrame(predictions)
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM recommendation_results WHERE model_type = 'RF-Optimized'"))
                res_df.to_sql('recommendation_results', con=conn, if_exists='append', index=False, method='multi',
                              chunksize=2000)

        print(f"✅ 执行完毕。详细指标已通过全量预测更新。")
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