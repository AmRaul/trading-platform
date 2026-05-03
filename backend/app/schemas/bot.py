from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class StrategyConfig(BaseModel):
    """
    Trading strategy configuration with strict validation.

    All parameters are validated to ensure safe trading practices.
    """
    order_count: int = Field(
        default=4,
        ge=1,
        le=10,
        description="Max pyramid orders (1-10)"
    )
    entry_size_usdt: float = Field(
        default=10.0,
        gt=0,
        le=10000,
        description="First order size in USDT (max 10,000)"
    )
    step_percent: float = Field(
        default=4.0,
        gt=0,
        le=50,
        description="Price step for next order in % (0-50%)"
    )
    leverage: int = Field(
        default=10,
        ge=1,
        le=125,
        description="Leverage multiplier (max 125x on Bybit)"
    )
    pyramiding_multiplier: float = Field(
        default=1.5,
        ge=1.0,
        le=3.0,
        description="Order size multiplier (1-3x)"
    )
    sl_initial: float = Field(
        default=5.0,
        gt=0,
        le=50,
        description="Initial stop-loss in % (0-50%)"
    )
    sl_after_order3: float = Field(
        default=2.0,
        gt=0,
        le=50,
        description="SL offset in profit after order 3 in % (0-50%)"
    )
    sl_breakeven_on_order2: bool = Field(
        default=True,
        description="Move SL to breakeven after order 2"
    )
    use_trailing: bool = Field(
        default=True,
        description="Enable trailing stop"
    )
    trailing_percent: float = Field(
        default=1.5,
        gt=0,
        le=20,
        description="Trailing stop distance in % (0-20%)"
    )
    sl_breakeven_plus: float = Field(
        default=0.5,
        ge=0,
        le=10,
        description="SL offset in profit after order 3+ in %"
    )
    tp_percent: float = Field(
        default=3.0,
        gt=0,
        le=100,
        description="Take profit in %"
    )

    @validator('entry_size_usdt')
    def validate_entry_size(cls, v):
        """Ensure entry size is reasonable"""
        if v < 10:
            raise ValueError('Entry size too small (min 10 USDT)')
        return v

    @validator('leverage')
    def validate_leverage(cls, v):
        """Warn about high leverage"""
        if v > 20:
            logger.warning(f"High leverage detected: {v}x - Extreme risk!")
        if v > 50:
            logger.error(f"Very high leverage: {v}x - Not recommended!")
        return v

    @validator('pyramiding_multiplier')
    def validate_multiplier(cls, v):
        if v > 2.5:
            logger.warning(f'High multiplier: {v} - final orders will be very large')
        return v

    @validator('step_percent')
    def validate_step(cls, v):
        """Ensure step is not too small or large"""
        if v < 0.5:
            raise ValueError('Step too small (min 0.5%) - too many orders possible')
        if v > 20:
            logger.warning(f'Large step: {v}% - orders might not trigger')
        return v

    @validator('sl_initial')
    def validate_sl_initial(cls, v):
        """Validate initial stop loss"""
        if v > 20:
            logger.warning(f'Large initial SL: {v}% - high risk per trade')
        return v

    @validator('trailing_percent')
    def validate_trailing(cls, v):
        """Validate trailing stop"""
        if v < 0.5:
            raise ValueError('Trailing too tight (min 0.5%) - will trigger too early')
        if v > 10:
            logger.warning(f'Wide trailing: {v}% - might give back too much profit')
        return v

    class Config:
        schema_extra = {
            "example": {
                "order_count": 4,
                "entry_size_usdt": 100,
                "step_percent": 4,
                "leverage": 10,
                "pyramiding_multiplier": 1.5,
                "sl_initial": 5,
                "sl_after_order3": 2,
                "sl_breakeven_plus": 0.5,
                "use_trailing": True,
                "trailing_percent": 1.5,
                "tp_percent": 3.0
            }
        }


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
        if len(v) < 6:  # Minimum: BTCUSDT = 7 chars
            raise ValueError('Invalid symbol format')
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
