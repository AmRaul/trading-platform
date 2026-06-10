from pybit.unified_trading import HTTP, WebSocket
from app.core.config import settings
from typing import Optional, Callable
import asyncio
import logging

logger = logging.getLogger(__name__)


class BybitClient:
    """Bybit API client for public data only (no API keys required)"""

    def __init__(self):
        self.testnet = settings.BYBIT_TESTNET
        self.http_client = HTTP(testnet=self.testnet)
        self.ws_client: Optional[WebSocket] = None

    def init_websocket(self, on_message: Callable):
        self.ws_client = WebSocket(
            testnet=self.testnet,
            channel_type="linear",
        )
        return self.ws_client

    async def get_ticker(self, symbol: str) -> dict:
        """Get current ticker price — runs sync pybit call in executor to avoid blocking event loop"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.http_client.get_tickers(category="linear", symbol=symbol)
            )
            if response["retCode"] == 0 and response["result"]["list"]:
                return response["result"]["list"][0]
            return {}
        except Exception as e:
            logger.error(f"Error getting ticker for {symbol}: {e}")
            return {}

    def subscribe_ticker(self, symbol: str, callback: Callable):
        """Subscribe to ticker updates via WebSocket"""
        if not self.ws_client:
            raise ValueError("WebSocket not initialized")

        self.ws_client.ticker_stream(
            symbol=symbol,
            callback=callback
        )


# Global instance
bybit_client = BybitClient()
