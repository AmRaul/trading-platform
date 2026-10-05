from pydantic import BaseModel, Field
from typing import List, Optional


class BacktestMetrics(BaseModel):
    total_return_pct: float
    avg_annual_return_pct: float
    max_drawdown_pct: float
    trades: int
    win_rate_pct: float
    stops: int
    full_grid_fills: int
    avg_trade_hours: float
    max_trade_days: float
    liquidations: int
    period_2021_2023_pct: float
    period_2024_2026_pct: float


class YearlyReturn(BaseModel):
    year: int
    return_pct: float


class EquityPoint(BaseModel):
    date: str
    equity: float
    drawdown_pct: float


class BacktestPeriod(BaseModel):
    start: str
    end: str


class ReadyStrategyBacktest(BaseModel):
    params: dict
    period: BacktestPeriod
    metrics: BacktestMetrics
    yearly: List[YearlyReturn]
    equity_curve: List[EquityPoint]


class VariantSummary(BaseModel):
    key: str
    name: str
    metrics: BacktestMetrics


class ReadyStrategyVariant(BaseModel):
    key: str
    name: str
    description: str
    first_order_pct_of_deposit: float
    bot_preset: dict
    backtest: ReadyStrategyBacktest


class ReadyStrategyBase(BaseModel):
    slug: str
    name: str
    summary: str
    symbol: str
    side: str
    timeframe: str
    launch_available: bool


class ReadyStrategyListItem(ReadyStrategyBase):
    variants: List[VariantSummary]


class LaunchRequest(BaseModel):
    variant_key: str
    # Депозит под стратегию: размер первого ордера = deposit × % варианта
    deposit_usdt: float = Field(gt=0, le=10_000_000)
    exchange: str = Field(default="bybit", pattern="^(cryptorg|bybit)$")
    account_id: Optional[int] = None
    bybit_account_id: Optional[int] = None


class ReadyStrategyDetail(ReadyStrategyBase):
    description: str
    entry_rules: List[str]
    exit_rules: List[str]
    risk_notes: List[str]
    backtest_assumptions: List[str]
    launch_blockers: List[str]
    variants: List[ReadyStrategyVariant]
