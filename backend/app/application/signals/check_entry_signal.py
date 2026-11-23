import time
from typing import Dict, Optional

from app.ports.market_data import MarketData
from app.domain.signals.entry_signal import (
    EXIT_EVALUATORS, EntrySignalResult, closed_candles, evaluate_entry,
)

# 1000 свечей — максимум одного запроса Bybit. Для MRC length=200 этого
# достаточно: на истории BTC 15m risk_zone по окну 1000 совпадает с расчётом
# по полной истории в 100% проверенных точек. Supertrend 15m + EMA50/EMA200 на 4h
# совпадают с исследованием на SOL/AVAX/LINK/ETH/XRP, кроме 1 бара из ~24 000 —
# в точке пересечения EMA50/EMA200 (разница 3e-7), см.
# services/backtester/research/verify_supertrend_live.py.
SIGNAL_CANDLES = 1000
TREND_CANDLES = 1000

INTERVAL_MS = {"1": 60_000, "3": 180_000, "5": 300_000, "15": 900_000, "30": 1_800_000,
               "60": 3_600_000, "120": 7_200_000, "240": 14_400_000, "D": 86_400_000}


class CheckEntrySignalUseCase:
    """Загружает закрытые свечи и проверяет сигнал входа для одного symbol/side/конфига."""

    def __init__(self, market_data: MarketData):
        self.market_data = market_data

    async def _candles(self, symbol: str, cfg: Dict, now_ms: int):
        tf = cfg.get("timeframe", "15")
        raw = await self.market_data.get_klines(symbol, tf, SIGNAL_CANDLES)
        signal_candles = closed_candles(raw, INTERVAL_MS[tf], now_ms)
        daily = None
        if cfg.get("type") == "donchian":
            # канал Donchian — по закрытым дневкам
            raw_d = await self.market_data.get_klines(symbol, "D", 250)
            daily = closed_candles(raw_d, INTERVAL_MS["D"], now_ms)
        return signal_candles, daily

    async def execute_exit(self, symbol: str, side: str, cfg: Dict, now_ms: Optional[int] = None) -> EntrySignalResult:
        """Сигнал выхода для открытой позиции (сейчас — только donchian)."""
        now_ms = now_ms or int(time.time() * 1000)
        signal_candles, daily = await self._candles(symbol, cfg, now_ms)
        return EXIT_EVALUATORS[cfg["type"]](side, signal_candles, daily, cfg)

    async def execute(self, symbol: str, side: str, cfg: Dict, now_ms: Optional[int] = None) -> EntrySignalResult:
        now_ms = now_ms or int(time.time() * 1000)
        signal_candles, daily = await self._candles(symbol, cfg, now_ms)
        if cfg.get("type") == "donchian":
            return evaluate_entry(side, signal_candles, daily, cfg)

        trend_candles = None
        if cfg.get("trend_ema_period"):
            ttf = cfg.get("trend_timeframe", "D")
            raw_trend = await self.market_data.get_klines(symbol, ttf, TREND_CANDLES)
            trend_candles = closed_candles(raw_trend, INTERVAL_MS[ttf], now_ms)

        return evaluate_entry(side, signal_candles, trend_candles, cfg)
