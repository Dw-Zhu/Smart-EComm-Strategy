### 数据传输拓扑说明

1. **用户终端 (Client Node)**：
   - **操作**：用户通过浏览器上传 10,000 条符合 `test.csv` 格式的原始数据集（包含 `user_id`、`item_id` 等 32 个特征维度）。
   - **传输协议**：通过 HTTP/HTTPS 发送文件流。
2. **前端展示层 (Frontend - Vue 3)**：
   - **组件**：由 `FileUpload.vue` 接收文件，通过 **Axios** 封装 `FormData`。
   - **职责**：作为数据传输的门户，向后端发送 POST 请求。
3. **后端网关层 (Backend - FastAPI)**：
   - **逻辑处理**：接收文件流，进行字段格式校验（如校验是否包含 `purchase_intent`、`interaction_rate` 等核心字段）。
   - **路由分发**：利用 **SQLAlchemy/PyMySQL** 驱动，将数据流转至存储层。
4. **数据持久层 (Storage - MySQL 8.0)**：
   - **维度存储**：数据首先进入 `dim_user` 和 `dim_item` 表。
   - **事实存储**：随后进入 `fact_user_behavior` 表，利用外键约束维护 `user_id` 和 `item_id` 的关联性。
5. **计算与算法层 (Analytics Engine)**：
   - **画像构建**：触发 **K-means** 聚类脚本，从 MySQL 读取特征并计算分群标签。
   - **标签回写**：更新 `usr_persona` 表中的多维度标签（如消费等级、活跃度），同时自动更新 `last_update` 时间戳。
   - **推荐计算**：**随机森林 (Random Forest)** 模型基于最新画像标签进行评分排序。
6. **反馈闭环 (Response Loop)**：
   - **数据回传**：后端将处理成功的状态及最终推荐列表以 JSON 格式返回。
   - **看板呈现**：Vue 前端更新用户画像雷达图及个性化推荐商品列表。

### 项目结构
Smart-EComm-Strategy/
├── backend-python/                # 【后端目录】Python 3.11 环境
│   ├── venv/                      # 虚拟环境 (已解决权限问题)
│   ├── main.py                    # 后端入口：FastAPI 路由与 CORS 配置
│   ├── requirements.txt           # 依赖清单：fastapi, pandas, scikit-learn, pyspark
│   ├── sql/
│   │   └── schema.sql             # MySQL 8.0 建表脚本
│   ├── src/                       # 核心逻辑层
│   │   ├── database.py            # SQLAlchemy 数据库引擎与连接池
│   │   ├── preprocessing/         # 数据预处理 (Pandas 入库 & PySpark 清洗)
│   │   ├── profiling/             # 算法：K-means 聚类画像构建
│   │   └── recommendation/        # 算法：随机森林重排序推荐
│   └── libs/
│       └── mysql-connector-j.jar  # PySpark 访问 MySQL 的驱动
│
├── frontend-vue/                  # 【前端目录】Vue 3 + Vite 环境
│   ├── src/
│   │   ├── api/                   # Axios 请求封装：对接后端 8000 端口
│   │   ├── components/            # 可复用组件 (如上传组件、画像图表)
│   │   ├── views/                 # 页面：数据中心、画像展示、推荐列表
│   │   └── App.vue                # 根组件：包含侧边栏导航逻辑
│   ├── package.json               # 前端依赖：vue, axios, element-plus, echarts
│   └── vite.config.ts             # 代理配置：解决开发环境跨域问题
│
└── data/                          # 【数据目录】
    ├── raw/                       # 原始 10,000 条 test.csv
    └── models/                    # 存储训练好的 .pkl 模型文件

# 构建虚拟环境
python3 -m venv venv
# 激活你的虚拟环境
source venv/bin/activate  
# 清华大学镜像地址
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
# 下载配置文件中的依赖
pip install -r requirements.txt
# 启动后端
python main.py