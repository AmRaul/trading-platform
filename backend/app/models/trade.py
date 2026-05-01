from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from app.core.database import Base


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=False, index=True)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=False, index=True)

    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)  # LONG or SHORT

    # Entry
    entry_price = Column(Float, nullable=False)
    average_price = Column(Float, nullable=False)
    total_size = Column(Float, nullable=False)

    # Exit
    exit_price = Column(Float, nullable=False)
    exit_reason = Column(String, nullable=False)  # SL_HIT, TRAILING_STOP, MANUAL_CLOSE

    # Performance
    pnl = Column(Float, nullable=False)
    pnl_percent = Column(Float, nullable=False)

    # Orders info
    total_orders = Column(Integer, nullable=False)

    # Timestamps
    opened_at = Column(DateTime(timezone=True), nullable=False)
    closed_at = Column(DateTime(timezone=True), server_default=func.now())

    # Additional info
    notes = Column(Text, nullable=True)
