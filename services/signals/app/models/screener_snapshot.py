from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class ScreenerSnapshot(Base):
    __tablename__ = "screener_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, nullable=False, index=True)
    scanned_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    avg_candle_size_pct = Column(Float, nullable=False)
    atr = Column(Float, nullable=False)
    volume_24h = Column(Float, nullable=False)
    volume_7d_avg = Column(Float, nullable=False, default=0.0)
    volume_ratio = Column(Float, nullable=False, default=0.0)
    volume_1h = Column(Float, nullable=False, default=0.0)
    funding_rate = Column(Float, nullable=False, default=0.0)
    price_change_24h_pct = Column(Float, nullable=False)
    high_24h = Column(Float, nullable=False, default=0.0)
    low_24h = Column(Float, nullable=False, default=0.0)
    open_interest = Column(Float, nullable=False, default=0.0)
    direction = Column(String, nullable=False)
    price_range_pct = Column(Float, nullable=True)
    last_price = Column(Float, nullable=False)
