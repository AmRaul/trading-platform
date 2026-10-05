import time
from typing import Dict, Optional

from app.ports.market_data import MarketData
from app.domain.signals.entry_signal import EntrySignalResult, evaluate_mrc_entry, closed_candles

# 1000 свечей — максимум одного запроса Bybit. Для MRC length=200 этого
# достаточно: на истории BTC 15m risk_zone по окну 1000 совпадает с расчётом
# по полной истории в 100% проверенных точек.
SIGNAL_CANDLES = 1000
TREND_CANDLES = 1000

INTERVAL_MS = {"1": 60_000, "3": 180_000, "5": 300_000, "15": 900_000, "30": 1_800_000,
               "60": 3_600_000, "120": 7_200_000, "240": 14_400_000, "D": 86_400_000}


class CheckEntrySignalUseCase:
    """Загружает закрытые свечи и проверяет сигнал входа для одного symbol/side/конфига."""

    def __init__(self, market_data: MarketData):
        self.market_data = market_data

    async def execute(self, symbol: str, side: str, cfg: Dict, now_ms: Optional[int] = None) -> EntrySignalResult:
        now_ms = now_ms or int(time.time() * 1000)

        tf = cfg.get("timeframe", "15")
        raw = await self.market_data.get_klines(symbol, tf, SIGNAL_CANDLES)
        signal_candles = closed_candles(raw, INTERVAL_MS[tf], now_ms)

        trend_candles = None
        if cfg.get("trend_ema_period"):
            ttf = cfg.get("trend_timeframe", "D")
            raw_trend = await self.market_data.get_klines(symbol, ttf, TREND_CANDLES)
            trend_candles = closed_candles(raw_trend, INTERVAL_MS[ttf], now_ms)

        return evaluate_mrc_entry(side, signal_candles, trend_candles, cfg)
