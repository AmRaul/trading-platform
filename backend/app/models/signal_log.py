from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class SignalLog(Base):
    __tablename__ = "signal_log"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)           # LONG / SHORT
    strategy = Column(String, nullable=False, default="MOMENTUM")  # MOMENTUM / REVERSAL
    entry_price = Column(Float, nullable=False)
    entry_time = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Условия при входе
    vol_1h_pct = Column(Float, nullable=False)
    price_range_pct = Column(Float, nullable=False)
    avg_candle_size_pct = Column(Float, nullable=False)
    price_change_24h_pct = Column(Float, nullable=False)
    funding_rate = Column(Float, nullable=False, default=0.0)
    open_interest = Column(Float, nullable=False, default=0.0)

    # Цены через 15/30/60 минут
    price_15m = Column(Float, nullable=True)
    price_30m = Column(Float, nullable=True)
    price_60m = Column(Float, nullable=True)

    # PnL в % (positive = прибыль)
    pnl_15m = Column(Float, nullable=True)
    pnl_30m = Column(Float, nullable=True)
    pnl_60m = Column(Float, nullable=True)

    status = Column(String, nullable=False, default="PENDING")  # PENDING / FILLED
