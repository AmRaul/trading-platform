from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class EntrySignalConfig(BaseModel):
    """Автоматический вход по сигналу индикатора вместо ручного/лимитного."""

    # mrc — цена в полосе MRC; supertrend — разворот Supertrend в сторону сделки
    type: str = Field(default="mrc", pattern="^(mrc|supertrend)$")
    timeframe: str = Field(default="15", pattern="^(1|3|5|15|30|60|120|240)$")  # Bybit kline interval, минуты
    st_period: int = Field(default=10, ge=2, le=100)
    st_mult: float = Field(default=3.0, gt=0, le=10)
    mrc_length: int = Field(default=200, ge=20, le=900)
    mrc_inner_mult: float = Field(default=1.0, gt=0, le=10)
    mrc_outer_mult: float = Field(default=2.415, gt=0, le=10)
    mrc_gradsize: float = Field(default=0.5, gt=0, le=5)
    mrc_source: str = Field(default="hlc3", pattern="^(hlc3|close|ohlc4)$")
    entry_band: int = Field(default=2, ge=1, le=3)
    # Фильтр тренда: LONG только если close > EMA на trend_timeframe, SHORT — ниже.
    # None — без фильтра.
    trend_ema_period: Optional[int] = Field(default=200, ge=2, le=500)
    # Доп. условие режима: LONG — EMA fast выше EMA trend_ema_period, SHORT — ниже
    trend_ema_fast: Optional[int] = Field(default=None, ge=2, le=500)
    trend_timeframe: str = Field(default="D", pattern="^(60|240|D)$")


class StrategyConfig(BaseModel):
    """Trading strategy configuration."""

    bot_type: str = Field(default="pyramiding", pattern="^(pyramiding|dca|straddle)$")

    order_count: int = Field(default=4, ge=1, le=10)
    entry_size_usdt: float = Field(default=10.0, gt=0, le=10000)
    step_percent: float = Field(default=4.0, gt=0, le=50)
    leverage: int = Field(default=10, ge=1, le=125)

    # Pyramiding-specific — multiplier applied to the LAST order's size
    # (calculate_next_order_size: last.size * multiplier). >1 grows each
    # add-on, <1 shrinks it (e.g. 0.9 → 90%, 81%, 72.9%...), 1.0 keeps it fixed.
    pyramiding_multiplier: float = Field(default=1.5, gt=0, le=3.0)
    sl_after_order3: float = Field(default=2.0, gt=0, le=50)
    sl_breakeven_on_order2: bool = Field(default=True)
    sl_breakeven_plus: float = Field(default=0.5, ge=0, le=10)

    # DCA-specific
    dca_multiplier: float = Field(default=1.0, ge=1.0, le=5.0)
    dca_multiplier_price: float = Field(default=1.0, ge=1.0, le=3.0)

    # Stop loss — None means disabled
    sl_initial: Optional[float] = Field(default=5.0, ge=0, le=50)

    # Common
    use_trailing: bool = Field(default=True)
    trailing_percent: float = Field(default=1.5, gt=0, le=20)
    tp_percent: float = Field(default=3.0, gt=0, le=100)
    cycle: bool = Field(default=False)

    # None — вход вручную/по лимиту; иначе бот ждёт сигнал (state SIGNAL)
    entry_signal: Optional[EntrySignalConfig] = None

    # Straddle (TODO/6): при запуске LONG и SHORT по entry_size_usdt; order_count,
    # step_percent, pyramiding_multiplier, trailing, tp_percent (100 — без тейка), cycle —
    # как у пирамидинга, для рабочей стороны. sl_* не используются.
    phase2_after_steps: int = Field(default=3, ge=1, le=10)
    add_stop_steps: float = Field(default=1.0, ge=0.1, le=3)
    time_stop_minutes: Optional[int] = Field(default=240, ge=1, le=60 * 24 * 7)
    max_rearms: int = Field(default=1, ge=0, le=10)

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
    # NEUTRAL — straddle (LONG и SHORT одновременно)
    side: str = Field(pattern="^(LONG|SHORT|NEUTRAL)$")
    config: StrategyConfig
    exchange: str = Field(default="cryptorg", pattern="^(cryptorg|bybit)$")
    account_id: Optional[int] = None
    bybit_account_id: Optional[int] = None

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
        """Ensure side is LONG, SHORT or NEUTRAL"""
        v = v.upper()
        if v not in ['LONG', 'SHORT', 'NEUTRAL']:
            raise ValueError('Side must be LONG, SHORT or NEUTRAL')
        return v

    @validator('config')
    def validate_straddle_side(cls, v, values):
        if (values.get('side') == 'NEUTRAL') != (v.bot_type == 'straddle'):
            raise ValueError('straddle bots use side NEUTRAL, other bots — LONG or SHORT')
        return v


class BotUpdate(BaseModel):
    name: Optional[str] = None
    symbol: Optional[str] = None
    side: Optional[str] = Field(default=None, pattern="^(LONG|SHORT|NEUTRAL)$")
    config: Optional[StrategyConfig] = None
    is_active: Optional[bool] = None
    exchange: Optional[str] = Field(default=None, pattern="^(cryptorg|bybit)$")
    account_id: Optional[int] = None
    bybit_account_id: Optional[int] = None


class BotResponse(BaseModel):
    id: int
    name: str
    symbol: str
    side: str
    config: dict
    state: str
    is_active: bool
    total_pnl: float
    exchange: str = "cryptorg"
    account_id: Optional[int] = None
    bybit_account_id: Optional[int] = None
    limit_entry_price: Optional[float] = None
    # straddle: состояние конструкции + виртуальная пара (live из Redis, иначе из БД)
    straddle: Optional[dict] = None
    created_at: datetime
    started_at: Optional[datetime]
    open_position: Optional[OpenPositionData] = None

    class Config:
        from_attributes = True
