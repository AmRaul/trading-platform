from typing import Dict, List
from app.services.bybit import bybit_client
import asyncio
import logging

logger = logging.getLogger(__name__)


class BybitMarketDataAdapter:
    """Adapts BybitClient to the MarketData port."""

    async def get_ticker(self, symbol: str) -> Dict:
        return await bybit_client.get_ticker(symbol)

    async def get_klines(self, symbol: str, interval: str, limit: int) -> List[Dict]:
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: bybit_client.http_client.get_kline(
                    category="linear",
                    symbol=symbol,
                    interval=interval,
                    limit=limit,
                )
            )
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
