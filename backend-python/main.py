from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import os
import time
from pathlib import Path
import shutil

# 导入核心逻辑模块
from src.preprocessing.data_loader import process_and_load_csv
from src.profiling.cluster_model import train_user_clusters
# 确保 rf_ranker.py 已经处理好相关逻辑
from src.recommendation.rf_ranker import train_recommendation_model, get_top_recommendations

# 导入基准 User-CF 模型类
from src.recommendation.baseline_user_cf import UserCFBaseline

# 导入评价函数
from src.recommendation.evaluate import evaluate_models

from fastapi import FastAPI, BackgroundTasks
from typing import Dict, Optional

from sqlalchemy import text

import pandas as pd
from src.database import engine


# 项目标题
app = FastAPI(title="Smart-EComm-Strategy 智慧电商后端引擎")

# 1. 配置跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局状态管理，用于前端轮询
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

        # 数据处理入库
        process_and_load_csv(str(file_path))
        return {"status": "success", "message": "文件上传并解析成功", "filename": unique_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/recommend/train")
async def train_model(background_tasks: BackgroundTasks, params: Optional[Dict] = None):
    """
    接收前端参数，若 params 为空则使用默认值 5
    """
    # 逻辑处理：如果前端没传 body，params 为 None，则设为空字典
    safe_params = params or {}

    # 尝试获取 top_n，如果没有则默认为 5
    top_n = safe_params.get("top_n", 5)

    # 同样可以获取阈值，如果没有则默认 0.6
    threshold = safe_params.get("threshold", 0.6)

    # 启动后台任务并透传参数
    background_tasks.add_task(rebuild_all_task, top_n=top_n, threshold=threshold)

    return {
        "status": "success",
        "message": f"全量重构流水线已启动 (参数: Top-{top_n}, Threshold-{threshold})"
    }

async def rebuild_all_task(top_n: int = 5, threshold: float = 0.6):
    """
    全量重构异步流水线：支持动态参数透传
    """
    global training_status
    training_status["is_running"] = True
    try:
        # 1. 智慧画像建模
        print("\n" + "=" * 30)
        print(">>> 步骤 1: 正在构建智慧画像 (K-Means)...")
        train_user_clusters()

        # 2. 基准模型计算
        # 使用动态传入的 top_n
        print(f">>> 步骤 2: 正在执行 User-CF 基准模型 (Top {top_n})...")
        cf_model = UserCFBaseline()
        cf_model.save_results_to_db(top_n=top_n)

        # 3. 核心推荐模型训练
        # 透传 top_n 和 threshold 参数给随机森林模型
        print(f">>> 步骤 3: 正在训练优化版随机森林推荐模型 (Top {top_n}, Threshold {threshold})...")
        train_recommendation_model(top_n=top_n, threshold=threshold)

        # 4. 实验对比评价
        print(">>> 步骤 4: 正在基于数据库真实行为生成实验对比指标...")
        evaluate_models()

        training_status["last_result"] = "Success"
        print("=" * 30)
        print(f"✅ 全量任务已圆满完成（参数：Top {top_n}, Threshold {threshold}）。")

    except Exception as e:
        print(f"❌ 任务执行中断: {str(e)}")
        training_status["last_result"] = f"Error: {str(e)}"
    finally:
        training_status["is_running"] = False


@app.post("/api/admin/rebuild-all")
async def rebuild_all(background_tasks: BackgroundTasks):
    if training_status["is_running"]:
        return {"status": "error", "message": "已有任务正在运行中"}

    background_tasks.add_task(rebuild_all_task)
    return {"status": "success", "message": "全量重构任务已在后台启动"}


@app.get("/api/user/profile/{user_id}")
async def get_user_profile(user_id: str):
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
async def get_recommend_trend_final(user_id: str):
    """
    汇总该用户在不同品类下的预测得分趋势
    """
    query = text("""
                    SELECT 
                        i.category as name, 
                        MAX(r.score) as value 
                    FROM recommendation_results r
                    JOIN dim_item i ON r.item_id = i.item_id
                    WHERE r.user_id = :uid AND r.model_type = 'RF-Optimized'
                    GROUP BY i.category
                    ORDER BY value DESC
                    LIMIT 10
                 """)
    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"uid": user_id})
            data = [dict(row._mapping) for row in result]

            # 保底逻辑：确保图表不为空
            if not data:
                data = [{"name": "暂无数据", "value": 0}]

            return {"status": "success", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/model/metrics")
async def get_model_metrics():
    """
    供前端调用，获取 model_metrics 表中的 Precision, Recall, F1 数据
    """
    query = text("SELECT model_type, precision_val, recall_val, f1_val FROM model_metrics")
    try:
        with engine.connect() as conn:
            result = conn.execute(query)
            data = [dict(row._mapping) for row in result]
            return {"status": "success", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# 画像分析独立接口
@app.post("/api/analyze/persona")
async def analyze_persona(background_tasks: BackgroundTasks):
    """
    独立触发用户画像分析任务
    """
    if training_status["is_running"]:
        return {"status": "error", "message": "已有任务正在运行中"}

    def run_task():
        global training_status
        training_status["is_running"] = True
        try:
            print("正在执行独立画像分析...")
            train_user_clusters() # 执行 K-Means 聚类
            training_status["last_result"] = "Success"
        except Exception as e:
            training_status["last_result"] = f"Error: {str(e)}"
        finally:
            training_status["is_running"] = False

    background_tasks.add_task(run_task)
    return {"status": "success", "message": "画像分析任务已在后台启动"}


async def recommend_train(background_tasks: BackgroundTasks):
    """
    独立触发推荐模型训练任务 (随机森林)
    """
    if training_status["is_running"]:
        return {"status": "error", "message": "已有任务正在运行中"}

    def run_task():
        global training_status
        training_status["is_running"] = True
        try:
            print("正在执行独立推荐模型训练...")
            # 执行你修改后的保守型训练逻辑
            success, msg = train_recommendation_model()
            if success:
                training_status["last_result"] = "Success"
            else:
                training_status["last_result"] = f"Error: {msg}"
        except Exception as e:
            training_status["last_result"] = f"Error: {str(e)}"
        finally:
            training_status["is_running"] = False

    background_tasks.add_task(run_task)
    return {"status": "success", "message": "推荐模型训练已在后台启动"}


@app.get("/api/stats/persona_distribution")
async def get_persona_distribution():
    """
    获取画像分布统计数据（用于前端饼图展示）
    """
    query = text("""
                 SELECT cluster_label as name, COUNT(*) as value
                 FROM usr_persona
                 GROUP BY cluster_label
                 """)
    try:
        with engine.connect() as conn:
            result = conn.execute(query)
            # 将数据转换为前端 ECharts 喜欢的 {name: '分群1', value: 10} 格式
            data = [dict(row._mapping) for row in result]

            # 简单的标签映射（可选，增强可读性）
            label_map = {0: "高价值活跃用户", 1: "潜力挖掘用户", 2: "流失风险用户", 3: "普通大众用户"}
            for item in data:
                cluster_id = item['name']
                item['name'] = label_map.get(cluster_id, f"分群 {cluster_id}")

            return {"status": "success", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/stats/consumption_level")
async def get_consumption_level():
    """
    获取消费等级分布
    """
    query = text("""
        SELECT consumption_level as name, COUNT(*) as value 
        FROM usr_persona 
        GROUP BY consumption_level
    """)
    try:
        with engine.connect() as conn:
            result = conn.execute(query)
            data = [dict(row._mapping) for row in result]
            return {"status": "success", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/stats/category_ranking")
async def get_category_ranking():
    """
    获取热门品类覆盖人数排名（已排除同一用户重复计入）
    """
    # 核心修改：使用 COUNT(DISTINCT user_id) 统计覆盖的人数而非总条数
    query = text("""
        SELECT category as name, COUNT(DISTINCT user_id) as value 
        FROM recommendation_results 
        WHERE model_type = 'RF-Optimized'
        GROUP BY category 
        ORDER BY value DESC 
        LIMIT 10
    """)
    try:
        with engine.connect() as conn:
            result = conn.execute(query)
            data = [dict(row._mapping) for row in result]
            return {"status": "success", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/stats/consumption_levels")
async def get_consumption_levels():
    """
    获取消费等级分布统计数据（用于前端图表展示）
    """
    # 这里的字段名需与你数据库 usr_persona 表中的消费等级字段一致
    query = text("""
                 SELECT consumption_level as name, COUNT(*) as value
                 FROM usr_persona
                 GROUP BY consumption_level
                 ORDER BY value DESC
                 """)
    try:
        with engine.connect() as conn:
            result = conn.execute(query)
            # 转换为前端 ECharts 通用的 [{name: '高消费', value: 120}, ...] 格式
            data = [dict(row._mapping) for row in result]

            # 如果数据库里存的是数字索引，可以在这里做个映射增强可读性
            # level_map = {0: '低消费', 1: '中等消费', 2: '高消费'}
            # for item in data:
            #     item['name'] = level_map.get(item['name'], item['name'])

            return {"status": "success", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/model/evaluate")
async def trigger_evaluation():
    """
    手动触发模型评估，生成 Precision, Recall, F1 数据
    """
    try:
        # 运行评价脚本，结果会自动存入 model_metrics 表
        evaluate_models()
        return {"status": "success", "message": "对比实验评估完成！"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/user/detail/{user_id}")
async def get_user_detail(user_id: str):
    query = text("""
        SELECT 
            u.user_id,
            COALESCE(p.consumption_level, '未知') as consumption_level,
            CASE 
                WHEN p.cluster_label = 0 THEN '高价值活跃用户'
                WHEN p.cluster_label = 1 THEN '潜力挖掘用户'
                WHEN p.cluster_label = 2 THEN '流失风险用户'
                ELSE '普通大众用户'
            END AS persona_tag,
            COALESCE(p.preferred_category, '多品类均衡') as preferred_category,
            COALESCE(p.activity_level, '新进/非活跃') as activity_level
        FROM dim_user u
        LEFT JOIN usr_persona p ON u.user_id = p.user_id
        WHERE u.user_id = :uid
    """)
    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"uid": user_id}).fetchone()
            if result:
                return {"status": "success", "data": dict(result._mapping)}
            return {"status": "error", "message": "未找到该用户"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 2. 修复推荐列表：增加全局热门商品保底
@app.get("/api/recommend/{user_id}")
async def get_user_recommendations(user_id: str):
    # 优先查 RF 结果，如果没有，则查询全局点击最高的商品作为保底
    query = text("""
        SELECT 
            r.item_id, 
            i.category, 
            r.score,
            r.rank
        FROM recommendation_results r
        JOIN dim_item i ON r.item_id = i.item_id
        JOIN dim_user u ON r.user_id = u.user_id
        WHERE r.user_id = :uid AND r.model_type = 'RF-Optimized'
        ORDER BY r.rank ASC 
        LIMIT 5
    """)
    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"uid": user_id})
            data = [dict(row._mapping) for row in result]
            return {"status": "success", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/recommend/{user_id}")
async def get_user_recommend_final(user_id: str):
    """
    以 recommendation_results 为主表，联查 dim_item 获取准确的品类信息
    """
    query = text("""
                 SELECT r.item_id,
                        i.category,
                        r.score,
                        r.rank
                 FROM recommendation_results r
                          JOIN dim_item i ON r.item_id = i.item_id
                          JOIN dim_user u ON r.user_id = u.user_id
                 WHERE r.user_id = :uid
                   AND r.model_type = 'RF-Optimized'
                 ORDER BY r.rank ASC LIMIT 5
                 """)
    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"uid": user_id})
            data = [dict(row._mapping) for row in result]

            # 保底逻辑：如果该用户没有模型结果，返回全局热门作为填充
            if not data:
                fallback_query = text("""
                                      SELECT item_id, category, 0.5 as score, 0 as rank
                                      FROM dim_item LIMIT 5
                                      """)
                data = [dict(row._mapping) for row in conn.execute(fallback_query)]

            return {"status": "success", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/model/kmeans_elbow")
async def get_kmeans_elbow():
    try:
        # 核心修正：使用 AS 将数据库字段名重命名为前端需要的 k 和 sse
        query = text("SELECT k_value AS k, sse_value AS sse FROM kmeans_metrics ORDER BY k_value ASC")
        with engine.connect() as conn:
            result = conn.execute(query)
            # 转化为列表对象
            data = [{"k": row.k, "sse": row.sse} for row in result]
            return {"status": "success", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/model/rf_sensitivity")
async def get_rf_sensitivity():
    """
    读取真实的随机森林阈值敏感度趋势 (由 train_recommendation_model 生成)
    """
    try:
        # 读取不同阈值下的精度、召回率和 F1 分数
        query = """
            SELECT threshold, precision_val as p, recall_val as r, f1_val as f 
            FROM rf_sensitivity_metrics 
            ORDER BY threshold ASC
        """
        df = pd.read_sql(query, engine)
        if df.empty:
            return {"status": "success", "data": []}
        return {"status": "success", "data": df.to_dict(orient='records')}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/model/kmeans_process")
async def get_kmeans_process():
    # 调用 cluster_model.py 中的新函数
    from src.profiling.cluster_model import get_kmeans_steps_data
    return get_kmeans_steps_data(n_clusters=4)

@app.post("/api/model/optimize")
async def optimize_model_alias(background_tasks: BackgroundTasks, params: Optional[Dict] = None):
    """
    前端 ModelEvaluation.vue 调用的调优接口别名
    """
    # 直接转发给已有的重构逻辑
    return await train_model(background_tasks, params)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)