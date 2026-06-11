from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class TrendSignalLog(Base):
    __tablename__ = "trend_signal_log"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)
    entry_price = Column(Float, nullable=False)
    entry_time = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    ema21_4h = Column(Float)
    ema21_1h = Column(Float)
    trend_4h = Column(String)
    pullback_1h = Column(Boolean)
    trigger_15m = Column(Boolean)
    stop_price = Column(Float)
    stop_pct = Column(Float)
    exit_price = Column(Float, nullable=True)
    exit_time = Column(DateTime(timezone=True), nullable=True)
    exit_reason = Column(String, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    duration_hrs = Column(Float, nullable=True)
    peak_pnl_pct = Column(Float, nullable=True)
    pyramid_count = Column(Integer, default=0)
    status = Column(String, nullable=False, default="OPEN")
