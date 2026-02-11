import gradio as gr
import pandas as pd
from src.preprocessing.data_loader import process_and_load_csv
from src.profiling.cluster_model import train_user_clusters
from src.database import get_engine


# --- 业务包装函数 ---
def handle_upload(file):
    """处理文件同步与预览"""
    if file is None:
        return None, "❌ 请先选择文件"

    # process_and_load_csv 接收文件路径并入库
    success, message = process_and_load_csv(file.name)

    if success:
        # Gradio 渲染 DataFrame 非常稳健，不需要 .astype(str)
        df_preview = pd.read_csv(file.name, nrows=5)
        return df_preview, f"✅ {message}"
    return None, f"❌ 同步失败: {message}"


def handle_profiling(n_clusters):
    """触发 K-means 聚类并展示结果"""
    success, msg = train_user_clusters(int(n_clusters))
    if success:
        engine = get_engine()
        # 从数据库读取最新的画像结果
        res_df = pd.read_sql("SELECT * FROM usr_persona LIMIT 10", engine)
        return res_df, f"✅ {msg}"
    return None, f"❌ 分析失败: {msg}"


# --- 构建 UI 界面 ---
with gr.Blocks(title="Smart-EComm-Strategy", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🛍️ Smart-EComm-Strategy 智慧电商策略系统")
    gr.Markdown("当前环境：Python 3.11 | 数据库：MySQL 8.0 | 前端：Gradio")

    with gr.Tabs():
        # 标签页 1：数据集成
        with gr.TabItem("📂 数据中心 (Data Hub)"):
            with gr.Row():
                file_input = gr.File(label="上传电商原始数据集 (test.csv)", file_types=[".csv"])
            with gr.Row():
                upload_btn = gr.Button("🚀 同步至数据库", variant="primary")

            preview_output = gr.DataFrame(label="数据预览 (Top 5)")
            status_output = gr.Textbox(label="系统日志")

            upload_btn.click(
                fn=handle_upload,
                inputs=[file_input],
                outputs=[preview_output, status_output]
            )

        # 标签页 2：算法分析
        with gr.TabItem("👤 用户画像 (Profiling)"):
            with gr.Row():
                cluster_slider = gr.Slider(2, 6, value=4, step=1, label="设置聚类中心数量 (K)")
            with gr.Row():
                profile_btn = gr.Button("🧠 执行 K-means 画像构建", variant="primary")

            persona_output = gr.DataFrame(label="画像标签结果 (部分展示)")
            profile_status = gr.Textbox(label="算法状态")

            profile_btn.click(
                fn=handle_profiling,
                inputs=[cluster_slider],
                outputs=[persona_output, profile_status]
            )

# 启动服务
if __name__ == "__main__":
    # Gradio 默认端口 7860，你可以改为 8501 保持习惯
    demo.launch(server_port=8501)