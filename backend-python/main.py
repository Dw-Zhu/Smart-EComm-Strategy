from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import os
import time
from pathlib import Path
import shutil

# 导入核心逻辑模块
from src.preprocessing.data_loader import process_and_load_csv
from src.profiling.cluster_model import train_user_clusters
# 确保 rf_ranker.py 已经改成了我刚才给你的多进程版本
from src.recommendation.rf_ranker import train_recommendation_model, get_top_recommendations

from sqlalchemy import text
from src.database import engine

app = FastAPI(title="SparkMiner 智慧电商后端引擎")

# 1. 配置跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 新增：全局状态管理，用于前端轮询
training_status = {"is_running": False, "last_result": None}

# 定义上传目录路径
UPLOAD_DIR = Path("temp_uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


@app.post("/api/data/upload")
async def upload_data(file: UploadFile = File(...)):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="仅支持上传 CSV 格式文件")

    file_ext = os.path.splitext(file.filename)[1]
    base_name = os.path.splitext(file.filename)[0]
    unique_name = f"{base_name}_{int(time.time())}{file_ext}"
    file_path = UPLOAD_DIR / unique_name

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        success, msg = process_and_load_csv(str(file_path))

        if success:
            df = pd.read_csv(file_path)
            preview_cols = ['user_id', 'item_id', 'category', 'interaction_rate', 'purchase_intent', 'label']
            available_cols = [c for c in preview_cols if c in df.columns]
            df_preview = df[available_cols].head(10).fillna("")

            return {
                "status": "success",
                "message": msg,
                "saved_filename": unique_name,
                "preview": df_preview.to_dict(orient="records")
            }
        else:
            if os.path.exists(file_path): os.remove(file_path)
            raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        if os.path.exists(file_path): os.remove(file_path)
        return {"status": "error", "message": str(e)}
    finally:
        file.file.close()


@app.post("/api/analyze/persona")
async def analyze_persona():
    success, msg = train_user_clusters(n_clusters=4)
    if success:
        return {"status": "success", "message": msg}
    else:
        raise HTTPException(status_code=500, detail=msg)


# --- 核心修改：异步训练任务包装函数 ---
def run_training_wrapper():
    """后台运行的包装函数，用于更新全局状态"""
    global training_status
    training_status["is_running"] = True
    # 调用优化后的多进程训练函数
    success, msg = train_recommendation_model()
    training_status["is_running"] = False
    training_status["last_result"] = {"success": success, "message": msg}


@app.post("/api/recommend/train")
async def train_model(background_tasks: BackgroundTasks):
    """
    步骤 3: 异步触发随机森林模型训练
    """
    if training_status["is_running"]:
        return {"status": "warning", "message": "模型训练已在后台运行中，请勿重复操作"}

    # 将耗时的多进程计算任务放入后台执行
    background_tasks.add_task(run_training_wrapper)

    return {
        "status": "success",
        "message": "模型训练已成功异步开启，您可以继续进行其他操作。"
    }


@app.get("/api/recommend/train/status")
async def get_train_status():
    """
    新增：供前端轮询训练状态
    """
    return training_status


# --- 后续接口保持不变 ---

@app.get("/api/recommend/{user_id}")
async def recommend(user_id: str):
    recommendations = get_top_recommendations(user_id, top_n=5)
    return {"status": "success", "data": recommendations}


@app.get("/api/stats/persona_distribution")
async def get_persona_distribution():
    query = "SELECT persona_tag as name, COUNT(*) as value FROM usr_persona GROUP BY persona_tag"
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            data = [dict(row._mapping) for row in result]
            return {"status": "success", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/consumption_levels")
async def get_consumption_levels():
    query = "SELECT consumption_level as name, COUNT(*) as value FROM usr_persona GROUP BY consumption_level ORDER BY name ASC"
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            data = []
            label_map = {0: '极低消费', 1: '低消费', 2: '中等消费', 3: '高消费'}
            for row in result:
                row_dict = dict(row._mapping)
                data.append(
                    {"name": label_map.get(row_dict['name'], f"等级 {row_dict['name']}"), "value": row_dict['value']})
            return {"status": "success", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/category_ranking")
async def get_category_ranking():
    query = "SELECT preferred_category as name, COUNT(*) as value FROM usr_persona GROUP BY preferred_category ORDER BY value DESC LIMIT 10"
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            data = [dict(row._mapping) for row in result]
            return {"status": "success", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/user/detail/{user_id}")
async def get_user_persona_detail(user_id: str):
    query = text("SELECT * FROM usr_persona WHERE user_id = :uid")
    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"uid": user_id}).fetchone()
            if result:
                return {"status": "success", "data": dict(result._mapping)}
            else:
                return {"status": "error", "message": "未找到该用户画像"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/system/status")
async def get_system_status():
    try:
        with engine.connect() as conn:
            res_persona = conn.execute(text("SELECT COUNT(*) FROM usr_persona")).scalar()
            res_user = conn.execute(text("SELECT COUNT(*) FROM dim_user")).scalar()
            return {"isUploaded": res_user > 0, "isProfiled": res_persona > 0}
    except Exception:
        return {"isUploaded": False, "isProfiled": False}


@app.get("/api/recommend/trend/{user_id}")
async def get_recommend_trend(user_id: str):
    query = text(
        "SELECT category as name, score as value, item_id FROM recommendation_results WHERE user_id = :uid ORDER BY score DESC LIMIT 20")
    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"uid": user_id})
            data = [dict(row._mapping) for row in result]
            return {"status": "success", "data": data if data else []}
    except Exception as e:
        return {"status": "error", "message": "获取趋势数据失败"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)