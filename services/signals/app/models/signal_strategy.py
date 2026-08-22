from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class SignalStrategy(Base):
    __tablename__ = "signal_strategies"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    is_builtin = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    range_min = Column(Float, nullable=True)
    range_max = Column(Float, nullable=True)
    change_min = Column(Float, nullable=True)
    change_max = Column(Float, nullable=True)
    vol_1h_min = Column(Float, nullable=True)
    side = Column(String, nullable=False, default="LONG")
    description = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
