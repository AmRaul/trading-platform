from typing import Callable, Awaitable, Dict, Set
from pybit.unified_trading import WebSocket
import asyncio
import logging

logger = logging.getLogger(__name__)


class BybitPriceStream:
    """Streams live prices from Bybit linear futures WebSocket."""

    EXCHANGE = "bybit"

    def __init__(self, testnet: bool = False):
        self._testnet = testnet
        self._ws: WebSocket | None = None
        self._subscribed: Set[str] = set()
        self._callbacks: Dict[str, Callable[[str, str, float], Awaitable[None]]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def _ensure_ws(self):
        if self._ws is None:
            self._ws = WebSocket(testnet=self._testnet, channel_type="linear")

    async def subscribe(self, symbol: str, callback: Callable[[str, str, float], Awaitable[None]]) -> None:
        if symbol in self._subscribed:
            self._callbacks[symbol] = callback
            return

        self._loop = asyncio.get_event_loop()
        self._callbacks[symbol] = callback
        self._ensure_ws()

        def on_message(message):
            asyncio.run_coroutine_threadsafe(
                self._handle(symbol, message), self._loop
            )

        self._ws.ticker_stream(symbol=symbol, callback=on_message)
        self._subscribed.add(symbol)
        logger.info(f"[bybit] subscribed to {symbol}")

    async def _handle(self, symbol: str, message: dict):
        try:
            data = message.get("data", {})
            price_str = data.get("lastPrice")
            if not price_str:
                return
            price = float(price_str)
            if price <= 0:
                return
            cb = self._callbacks.get(symbol)
            if cb:
                await cb(self.EXCHANGE, symbol, price)
        except Exception as e:
            logger.error(f"[bybit] price handle error {symbol}: {e}")

    async def unsubscribe(self, symbol: str) -> None:
        self._subscribed.discard(symbol)
        self._callbacks.pop(symbol, None)

    async def close(self) -> None:
        if self._ws:
            try:
                self._ws.exit()
            except Exception:
                pass
            self._ws = None
        self._subscribed.clear()
        self._callbacks.clear()
