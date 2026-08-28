from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PositionResponse(BaseModel):
    id: int
    bot_id: int
    symbol: str
    side: str
    total_size: float
    average_price: Optional[float]
    current_sl: Optional[float]
    trailing_sl: Optional[float]
    unrealized_pnl: float
    realized_pnl: float
    order_count: int
    is_open: bool
    is_bot_managed: bool
    trailing_enabled: bool
    opened_at: datetime
    closed_at: Optional[datetime]

    class Config:
        from_attributes = True


class PositionManagedUpdate(BaseModel):
    is_bot_managed: bool


class PositionTrailingUpdate(BaseModel):
    trailing_enabled: bool
