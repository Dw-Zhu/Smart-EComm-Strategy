from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import os

app = FastAPI(title="EC-UPRS 大数据用户画像与推荐系统 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. 路径自动探测逻辑
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(os.path.dirname(CURRENT_DIR), "data", "test.csv")


# 2. 全局初始化加载函数
def load_initial_data():
    if os.path.exists(DATA_PATH):
        print(f"✅ 成功加载数据文件: {DATA_PATH}")
        return pd.read_csv(DATA_PATH)
    else:
        print(f"❌ 未找到文件: {DATA_PATH}，启动模拟数据模式")
        return pd.DataFrame({
            'user_id': ['U00000001'], 'item_id': ['I00015796'],
            'age': [18], 'gender': [0], 'user_level': [1],
            'purchase_freq': [20], 'social_influence': [312.14],
            'label': [0], 'category': ['服饰鞋包'],
            'purchase_intent': [15.0], 'pv_count': [10],
            'collect_num': [5], 'add2cart': [1], 'interaction_rate': [0.5]
        })


# 核心：在全局作用域定义 df
df = load_initial_data()


@app.get("/api/v1/user/profile/{user_id}")
async def get_user_profile(user_id: str):
    global df
    user_data = df[df['user_id'] == user_id]
    if user_data.empty:
        user_data = df.head(1)

    row = user_data.iloc[0]
    return {
        "user_id": str(row['user_id']),
        "age": int(row['age']),
        "gender": int(row['gender']),
        "user_level": int(row['user_level']),
        "is_active_user": bool(row['purchase_freq'] > 10),
        "social_influence": float(row['social_influence']),
        "cluster_id": int(row['label'])
    }


@app.get("/api/v1/recommend/{user_id}")
async def get_recommendations(user_id: str):
    global df
    user_data = df[df['user_id'] == user_id]
    target_label = user_data.iloc[0]['label'] if not user_data.empty else 0
    recommendations = df[df['label'] == target_label].sort_values(by='purchase_intent', ascending=False).head(6)

    res = []
    for _, row in recommendations.iterrows():
        res.append({
            "item_id": str(row['item_id']),
            "category": str(row['category']),
            "rec_score": float(row.get('purchase_intent', 10.0) * 5)
        })
    return res


# 🎯 修复后的计算明细接口
@app.get("/api/v1/recommend/detail/{user_id}")
async def get_recommend_detail(user_id: str):
    # 关键点：必须声明全局引用，否则报 NameError
    global df

    user_data = df[df['user_id'] == user_id]
    if user_data.empty:
        recommendations = df.head(10)
    else:
        target_label = user_data.iloc[0]['label']
        recommendations = df[df['label'] == target_label].sort_values(
            by='purchase_intent', ascending=False
        ).head(10)

    res = []
    for _, row in recommendations.iterrows():
        base_intent = float(row.get('purchase_intent', 10.0))
        # 拆解评分逻辑
        p_score = round(base_intent * 5.8, 1)
        b_score = round(float(row.get('interaction_rate', 0.5)) * 15, 1)
        t_score = round((p_score * 0.6) + (b_score * 0.4), 1)

        res.append({
            "item_id": str(row['item_id']),
            "category": str(row['category']),
            "profile_score": p_score,
            "behavior_score": b_score,
            "total_score": t_score,
            "star": round(t_score / 20, 1)
        })
    return res


@app.get("/api/v1/stats/cluster_distribution")
async def get_cluster_stats():
    global df
    stats = df['label'].value_counts().sort_index().to_dict()
    return [{"cluster_id": k, "count": v} for k, v in stats.items()]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
