from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=False, index=True)
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=False, index=True)

    # Order details
    exchange_order_id = Column(String, nullable=True, index=True)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)  # BUY or SELL

    # Execution
    size = Column(Float, nullable=False)  # Order size
    price = Column(Float, nullable=False)  # Execution price

    # Type
    order_type = Column(String, default="MARKET")  # MARKET, LIMIT
    order_number = Column(Integer, nullable=False)  # 1, 2, 3, 4 (pyramid level)

    # Status
    status = Column(String, default="PENDING")  # PENDING, FILLED, REJECTED, CANCELLED

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    filled_at = Column(DateTime(timezone=True), nullable=True)
