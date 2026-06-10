from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class StrategyConfig(BaseModel):
    """Trading strategy configuration."""

    bot_type: str = Field(default="pyramiding", pattern="^(pyramiding|dca)$")

    order_count: int = Field(default=4, ge=1, le=10)
    entry_size_usdt: float = Field(default=10.0, gt=0, le=10000)
    step_percent: float = Field(default=4.0, gt=0, le=50)
    leverage: int = Field(default=10, ge=1, le=125)

    # Pyramiding-specific
    pyramiding_multiplier: float = Field(default=1.5, ge=1.0, le=3.0)
    sl_after_order3: float = Field(default=2.0, gt=0, le=50)
    sl_breakeven_on_order2: bool = Field(default=True)
    sl_breakeven_plus: float = Field(default=0.5, ge=0, le=10)

    # DCA-specific
    dca_multiplier: float = Field(default=1.0, ge=1.0, le=5.0)
    dca_active_orders: int = Field(default=3, ge=1, le=10)
    dca_multiplier_price: float = Field(default=1.0, ge=1.0, le=3.0)

    # Stop loss — None means disabled
    sl_initial: Optional[float] = Field(default=5.0, ge=0, le=50)

    # Common
    use_trailing: bool = Field(default=True)
    trailing_percent: float = Field(default=1.5, gt=0, le=20)
    tp_percent: float = Field(default=3.0, gt=0, le=100)
    cycle: bool = Field(default=False)

    @validator('entry_size_usdt')
    def validate_entry_size(cls, v):
        if v < 10:
            raise ValueError('Entry size too small (min 10 USDT)')
        return v

    @validator('leverage')
    def validate_leverage(cls, v):
        if v > 20:
            logger.warning(f"High leverage detected: {v}x - Extreme risk!")
        if v > 50:
            logger.error(f"Very high leverage: {v}x - Not recommended!")
        return v

    @validator('step_percent')
    def validate_step(cls, v):
        if v < 0.5:
            raise ValueError('Step too small (min 0.5%)')
        return v

    @validator('trailing_percent')
    def validate_trailing(cls, v):
        if v < 0.5:
            raise ValueError('Trailing too tight (min 0.5%)')
        return v


class OpenPositionData(BaseModel):
    average_price: Optional[float] = None
    current_sl: Optional[float] = None
    total_size: float
    order_count: int
    unrealized_pnl: float
    last_order_price: Optional[float] = None
    opened_at: datetime

    class Config:
        from_attributes = True


class BotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    symbol: str = Field(min_length=1, max_length=20)
    side: str = Field(pattern="^(LONG|SHORT)$")
    config: StrategyConfig

    @validator('name')
    def validate_name(cls, v):
        """Ensure name is not empty or just whitespace"""
        if not v.strip():
            raise ValueError('Name cannot be empty')
        return v.strip()

    @validator('symbol')
    def validate_symbol(cls, v):
        """Validate trading symbol format"""
        v = v.upper().strip()
        if not v.endswith('USDT'):
            raise ValueError('Only USDT pairs supported (e.g., BTCUSDT)')
        return v

    @validator('side')
    def validate_side(cls, v):
        """Ensure side is LONG or SHORT"""
        v = v.upper()
        if v not in ['LONG', 'SHORT']:
            raise ValueError('Side must be either LONG or SHORT')
        return v


class BotUpdate(BaseModel):
    name: Optional[str] = None
    symbol: Optional[str] = None
    side: Optional[str] = Field(default=None, pattern="^(LONG|SHORT)$")
    config: Optional[StrategyConfig] = None
    is_active: Optional[bool] = None


class BotResponse(BaseModel):
    id: int
    name: str
    symbol: str
    side: str
    config: dict
    state: str
    is_active: bool
    total_pnl: float
    created_at: datetime
    started_at: Optional[datetime]
    open_position: Optional[OpenPositionData] = None

    class Config:
        from_attributes = True
