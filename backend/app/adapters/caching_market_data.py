"""Кэш свечей на один прогон (пакетная сверка): одни и те же минутки монеты не качаются
заново для каждой сделки. Живёт столько, сколько объект, — между запросами не хранится."""
from typing import Dict, List, Optional, Tuple

from app.ports.market_data import MarketData


class CachingMarketData:
    def __init__(self, market: MarketData):
        self.market = market
        self._klines: Dict[Tuple, List[Dict]] = {}
        # (symbol, interval) -> свечи по времени открытия и покрытые отрезки [start, end]
        self._candles: Dict[Tuple[str, str], Dict[int, Dict]] = {}
        self._covered: Dict[Tuple[str, str], List[Tuple[int, int]]] = {}
        self.fetches = 0  # сколько раз реально ходили на биржу за диапазоном — для тестов и логов

    async def get_ticker(self, symbol: str):
        return await self.market.get_ticker(symbol)

    async def get_klines(self, symbol: str, interval: str, limit: int, end_ms: Optional[int] = None):
        key = (symbol, interval, limit, end_ms)
        if key not in self._klines:
            self._klines[key] = await self.market.get_klines(symbol, interval, limit, end_ms=end_ms)
        return self._klines[key]

    async def get_klines_range(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> List[Dict]:
        key = (symbol, interval)
        if not any(s <= start_ms and end_ms <= e for s, e in self._covered.get(key, [])):
            candles = await self.market.get_klines_range(symbol, interval, start_ms, end_ms)
            self.fetches += 1
            store = self._candles.setdefault(key, {})
            for c in candles:
                store[c["timestamp"]] = c
            if candles:
                # покрыто только то, что реально пришло (длинный диапазон биржа может отдать не целиком)
                self._covered.setdefault(key, []).append((max(start_ms, candles[0]["timestamp"]), end_ms))
        store = self._candles.get(key, {})
        return [store[t] for t in sorted(store) if start_ms <= t <= end_ms]
