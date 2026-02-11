from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 1. 配置数据库连接
# 确保密码正确。MySQL 8.0 默认使用 utf8mb4 编码
SQLALCHEMY_DATABASE_URL = "mysql+pymysql://root:zhudawang@localhost:3306/Smart_EComm_Strategy?charset=utf8mb4"

# 2. 创建引擎
# 针对 MySQL 8.0 的长连接优化
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=15,             # 考虑到 10,000 条数据的并发写入，略微调大连接池
    max_overflow=25,
    pool_recycle=3600,
    pool_pre_ping=True        # 每次从池中取出连接前先检查是否可用，防止 MySQL 8.0 超时断线
)

# 3. 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 4. 声明 ORM 基类
Base = declarative_base()

# 5. 数据库依赖注入
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()