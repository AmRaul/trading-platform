from sqlalchemy import Column, Integer, String, Boolean, JSON, DateTime, Float
from sqlalchemy.sql import func
from app.core.database import Base


class Bot(Base):
    __tablename__ = "bots"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    symbol = Column(String, nullable=False, index=True)  # e.g. BTCUSDT
    side = Column(String, nullable=False)  # LONG or SHORT

    # Strategy configuration
    config = Column(JSON, nullable=False)
    # Example:
    # {
    #   "order_count": 4,
    #   "entry_size": 0.25,
    #   "step_percent": 4,
    #   "leverage": 10,
    #   "pyramiding_multiplier": 1.5,
    #   "sl_initial": 5,
    #   "sl_dynamic_offset": 2,
    #   "use_trailing": true,
    #   "trailing_percent": 1.5
    # }

    # State
    state = Column(String, default="IDLE")  # IDLE, ENTRY, PYRAMIDING, EXIT
    is_active = Column(Boolean, default=False)

    # Stats
    total_pnl = Column(Float, default=0.0)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    stopped_at = Column(DateTime(timezone=True), nullable=True)
