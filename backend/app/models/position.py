from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=False, index=True)

    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)  # LONG or SHORT

    # Position info
    total_size = Column(Float, default=0.0)  # Total position size in base currency
    average_price = Column(Float, nullable=True)  # Average entry price

    # Stop loss
    current_sl = Column(Float, nullable=True)
    trailing_sl = Column(Float, nullable=True)

    # PnL
    unrealized_pnl = Column(Float, default=0.0)
    realized_pnl = Column(Float, default=0.0)

    # Orders count
    order_count = Column(Integer, default=0)

    # Status
    is_open = Column(Boolean, default=True)

    # Timestamps
    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
