from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class TrendSymbol(Base):
    __tablename__ = "trend_symbols"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, unique=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
