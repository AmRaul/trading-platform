from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class OrderResponse(BaseModel):
    id: int
    position_id: int
    bot_id: int
    exchange_order_id: Optional[str]
    symbol: str
    side: str
    size: float
    price: float
    order_type: str
    order_number: int
    status: str
    created_at: datetime
    filled_at: Optional[datetime]

    class Config:
        from_attributes = True
