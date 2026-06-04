from dataclasses import dataclass
from datetime import datetime


@dataclass
class ScreenerCandidate:
    symbol: str
    avg_candle_size_pct: float   # средний размер 1m свечи (H-L)/L * 100
    atr: float                   # ATR(14) на 1m
    volume_24h: float            # оборот за 24h в USDT
    volume_7d_avg: float
    volume_ratio: float          # volume_24h / volume_7d_avg
    volume_1h: float             # оборот последнего закрытого часа в USDT
    funding_rate: float
    price_change_24h_pct: float
    high_24h: float
    low_24h: float
    open_interest: float         # открытый интерес в USDT
    direction: str               # LONG / SHORT / FLAT
    price_range_pct: float | None  # где цена в диапазоне дня: 0% = на лоу, 100% = на хае
    last_price: float
    scanned_at: datetime
