from sqlalchemy import Column, Integer, String, Boolean, JSON, DateTime, Float
from sqlalchemy.sql import func
from app.core.database import Base


class Bot(Base):
    __tablename__ = "bots"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    symbol = Column(String, nullable=False, index=True)  # e.g. BTCUSDT
    side = Column(String, nullable=False)  # LONG or SHORT

    config = Column(JSON, nullable=False)

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
