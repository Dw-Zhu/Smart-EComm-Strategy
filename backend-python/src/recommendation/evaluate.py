import pandas as pd
import numpy as np
from sqlalchemy import text
from src.database import engine


def evaluate_models():
    """
    核心评价函数：直接对比数据库中的真实行为与模型生成的推荐结果
    """
    try:
        print("🔍 开始从数据库提取评测数据进行离线评估...")

        # 1. 加载真值 (Ground Truth)
        # 使用 CAST 确保 user_id 和 item_id 统一为字符类型，防止匹配失败
        true_query = text("""
                          SELECT CAST(user_id AS CHAR) as user_id,
                                 CAST(item_id AS CHAR) as item_id
                          FROM fact_user_behavior
                          WHERE label = 1
                             OR purchase_intent = 1
                          """)

        with engine.connect() as conn:
            true_df = pd.read_sql(true_query, conn)

        if true_df.empty:
            print("❌ 评价失败：数据库中没有 label=1 的真实购买数据，请检查数据导入状态。")
            return

        # 转换为集合映射以加速匹配: {user_id: {item_id1, item_id2...}}
        true_interactions = true_df.groupby('user_id')['item_id'].apply(set).to_dict()
        print(f"📊 评估诊断：成功加载 {len(true_interactions)} 个用户的真实购买记录。")

    except Exception as e:
        print(f"❌ 数据库读取异常: {e}")
        return

    # 2. 定义待评估的模型
    models = ['User-CF', 'RF-Optimized']
    metrics_results = []

    for model in models:
        # 读取模型生成的推荐结果，同样进行类型转换
        query = text("""
                     SELECT CAST(user_id AS CHAR) as user_id,
                            CAST(item_id AS CHAR) as item_id
                     FROM recommendation_results
                     WHERE model_type = :mtype
                     """)

        with engine.connect() as conn:
            pred_df = pd.read_sql(query, conn, params={"mtype": model})

        if pred_df.empty:
            print(f"⚠️ 警告：数据库中未找到模型 {model} 的推荐数据。")
            continue

        # 转换为字典格式进行对比
        pred_dict = pred_df.groupby('user_id')['item_id'].apply(list).to_dict()
        precisions, recalls = [], []

        # 3. 核心指标计算逻辑：逐个用户对比
        for user_id, true_items in true_interactions.items():
            if user_id in pred_dict:
                pred_items = set(pred_dict[user_id])
                # 计算交集，即模型成功预测出的商品
                hit_items = true_items.intersection(pred_items)

                # Precision: 推荐出的结果中有多少是用户真正购买的
                precisions.append(len(hit_items) / len(pred_items) if len(pred_items) > 0 else 0)
                # Recall: 用户买过的商品中有多少被系统成功推荐了
                recalls.append(len(hit_items) / len(true_items) if len(true_items) > 0 else 0)
            else:
                # 若模型未覆盖该用户，则该用户指标记为 0
                precisions.append(0)
                recalls.append(0)

        # 4. 计算所有用户的平均指标
        p = np.mean(precisions) if precisions else 0
        r = np.mean(recalls) if recalls else 0
        f1 = (2 * p * r) / (p + r) if (p + r) > 0 else 0

        metrics_results.append({
            'model_type': model,
            'precision_val': p,
            'recall_val': r,
            'f1_val': f1
        })

        hit_user_count = sum(1 for x in precisions if x > 0)
        print(f"✅ {model} 评估完成：命中用户数={hit_user_count}, P={p:.4f}, R={r:.4f}")

    # 5. 结果持久化入库供前端展示
    if metrics_results:
        m_df = pd.DataFrame(metrics_results)
        try:
            with engine.begin() as conn:
                # 清理旧指标并存入最新重构任务的指标
                conn.execute(text("DELETE FROM model_metrics"))
                m_df.to_sql('model_metrics', con=conn, if_exists='append', index=False)
            print("🚀 全量实验对比指标已成功更新至数据库 model_metrics 表。")
        except Exception as e:
            print(f"❌ 结果写入失败: {e}")


if __name__ == "__main__":
    evaluate_models()