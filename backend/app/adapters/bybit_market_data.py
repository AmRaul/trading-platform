from typing import Dict, List, Optional
from app.services.bybit import bybit_client
import asyncio
import logging

logger = logging.getLogger(__name__)

KLINES_PAGE = 1000          # максимум свечей в одном запросе Bybit
KLINES_MAX_PAGES = 60       # ~41 день минуток — хватит на самую долгую сделку бэктеста (30 дней)


class BybitMarketDataAdapter:
    """Adapts BybitClient to the MarketData port."""

    async def get_ticker(self, symbol: str) -> Dict:
        return await bybit_client.get_ticker(symbol)

    async def get_klines(self, symbol: str, interval: str, limit: int, end_ms: Optional[int] = None) -> List[Dict]:
        """Последние limit свечей (от новой к старой, как отдаёт Bybit); с end_ms — до этого момента."""
        params = {"category": "linear", "symbol": symbol, "interval": interval, "limit": limit}
        if end_ms is not None:
            params["end"] = end_ms
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: bybit_client.http_client.get_kline(**params))
            if response["retCode"] != 0:
                logger.error(f"Bybit klines error for {symbol}: {response}")
                return []

            raw = response["result"]["list"]
            candles = []
            for item in raw:
                candles.append({
                    "timestamp": int(item[0]),
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                })
            return candles
        except Exception as e:
            logger.error(f"Error fetching klines for {symbol}: {e}")
            return []

    async def get_klines_range(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> List[Dict]:
        """Свечи с открытием в [start_ms, end_ms], по возрастанию времени — постранично назад от end_ms."""
        out: Dict[int, Dict] = {}
        cursor = end_ms
        for _ in range(KLINES_MAX_PAGES):
            page = await self.get_klines(symbol, interval, KLINES_PAGE, end_ms=cursor)
            if not page:
                break
            for c in page:
                if start_ms <= c["timestamp"] <= end_ms:
                    out[c["timestamp"]] = c
            oldest = min(c["timestamp"] for c in page)
            if oldest <= start_ms or len(page) < KLINES_PAGE:
                break
            cursor = oldest - 1
        return [out[t] for t in sorted(out)]
