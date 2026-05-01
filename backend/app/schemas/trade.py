from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class TradeResponse(BaseModel):
    id: int
    bot_id: int
    position_id: int
    symbol: str
    side: str
    entry_price: float
    average_price: float
    total_size: float
    exit_price: float
    exit_reason: str
    pnl: float
    pnl_percent: float
    total_orders: int
    opened_at: datetime
    closed_at: datetime
    notes: Optional[str]

    class Config:
        from_attributes = True
