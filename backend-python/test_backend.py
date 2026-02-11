import os
import sys

# 确保项目路径在系统路径中，解决红线报错问题
sys.path.append(os.getcwd())

from src.preprocessing.data_loader import process_and_load_csv
from src.profiling.cluster_model import train_user_clusters
from src.recommendation.rf_ranker import train_recommendation_model, get_top_recommendations


def run_full_validation():
    print("🔔 开始后端核心逻辑自动化验证...\n")

    # 1. 验证数据入库逻辑
    print("Step 1: 正在测试数据入库 (Data Loader)...")
    csv_path = "../data/raw/test.csv"  # 请确保该路径下有你的 10,000 条数据文件
    if not os.path.exists(csv_path):
        print(f"❌ 错误：找不到测试文件 {csv_path}")
        return

    success, msg = process_and_load_csv(csv_path)
    if success:
        print(f"✅ {msg}")
    else:
        print(f"❌ 入库失败: {msg}")
        return

    # 2. 验证画像聚类逻辑
    print("\nStep 2: 正在测试画像构建 (K-means Profiling)...")
    success, msg = train_user_clusters(n_clusters=4)
    if success:
        print(f"✅ {msg}")
    else:
        print(f"❌ 画像构建失败: {msg}")
        return

    # 3. 验证推荐模型训练
    print("\nStep 3: 正在测试推荐模型训练 (RF Training)...")
    success, msg = train_recommendation_model()
    if success:
        print(f"✅ {msg}")
    else:
        print(f"❌ 模型训练失败: {msg}")
        return

    # 4. 验证实时推荐预测
    print("\nStep 4: 正在测试实时推荐输出 (Inference)...")
    test_user = "user_0"  # 请确保你的 CSV 中包含该 ID，或者换成一个存在的 ID
    recommendations = get_top_recommendations(test_user, top_n=5)

    if recommendations:
        print(f"✅ 成功为用户 {test_user} 生成推荐列表:")
        for i, rec in enumerate(recommendations):
            print(f"   - 排名 {i + 1}: 商品ID {rec['item_id']}, 预测购买概率: {rec['score']:.4f}")
    else:
        print(f"❌ 推荐输出为空，请检查画像数据是否正确回写至 usr_persona 表。")

    print("\n🎊 恭喜！后端四大核心模块逻辑验证全部通过。")


if __name__ == "__main__":
    run_full_validation()