from sqlalchemy import Column, String, Integer, Float, DECIMAL, ForeignKey, Boolean, TIMESTAMP, text
from src.database import Base


class UserPersona(Base):
    """用户画像模型"""
    __tablename__ = "usr_persona"

    user_id = Column(String(50), ForeignKey("dim_user.user_id"), primary_key=True)
    cluster_label = Column(Integer)
    persona_tag = Column(String(100))
    loyalty_score = Column(Float)
    is_churn_risk = Column(Boolean, default=False)
    activity_level = Column(String(20))
    last_update = Column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'))
    # ... 其他字段 (根据 SQL 持续补充)