from typing import Dict, List
from pybit.unified_trading import HTTP
from app.core.config import settings
import asyncio
import logging

logger = logging.getLogger(__name__)


class BybitMarketDataAdapter:
    def __init__(self):
        self._http = HTTP(testnet=settings.BYBIT_TESTNET)

    async def get_ticker(self, symbol: str) -> Dict:
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._http.get_tickers(category="linear", symbol=symbol)
            )
            if response["retCode"] == 0 and response["result"]["list"]:
                return response["result"]["list"][0]
            return {}
        except Exception as e:
            logger.error(f"get_ticker {symbol}: {e}")
            return {}

    async def get_klines(self, symbol: str, interval: str, limit: int) -> List[Dict]:
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._http.get_kline(category="linear", symbol=symbol, interval=interval, limit=limit)
            )
            if response["retCode"] != 0:
                return []
            return [
                {"timestamp": int(i[0]), "open": float(i[1]), "high": float(i[2]),
                 "low": float(i[3]), "close": float(i[4]), "volume": float(i[5])}
                for i in response["result"]["list"]
            ]
        except Exception as e:
            logger.error(f"get_klines {symbol}: {e}")
            return []

    def get_all_tickers(self) -> list:
        try:
            response = self._http.get_tickers(category="linear")
            if response["retCode"] != 0:
                return []
            tickers = [t for t in response["result"]["list"] if t["symbol"].endswith("USDT")]
            tickers.sort(key=lambda t: float(t.get("turnover24h", 0)), reverse=True)
            return tickers
        except Exception as e:
            logger.error(f"get_all_tickers: {e}")
            return []
