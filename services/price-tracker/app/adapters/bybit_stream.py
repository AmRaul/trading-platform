from typing import Callable, Awaitable, Dict, Set
from pybit.unified_trading import WebSocket
import asyncio
import logging
import threading
import time

logger = logging.getLogger(__name__)


class BybitPriceStream:
    """Streams live prices from Bybit linear futures WebSocket."""

    EXCHANGE = "bybit"
    # Нет ни одного сообщения дольше этого — считаем сокет мёртвым
    STALE_AFTER = 90
    WATCHDOG_INTERVAL = 30

    def __init__(self, testnet: bool = False):
        self._testnet = testnet
        self._ws: WebSocket | None = None
        self._subscribed: Set[str] = set()
        self._callbacks: Dict[str, Callable[[str, str, float], Awaitable[None]]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_message = time.monotonic()
        self._watchdog_task: asyncio.Task | None = None
        # Сокет пересоздаётся из watchdog-потока — не даём subscribe лезть в него параллельно
        self._ws_lock = threading.Lock()

    def _ensure_ws(self):
        if self._ws is None:
            self._ws = WebSocket(testnet=self._testnet, channel_type="linear")

    async def subscribe(self, symbol: str, callback: Callable[[str, str, float], Awaitable[None]]) -> None:
        if symbol in self._subscribed:
            self._callbacks[symbol] = callback
            return

        self._loop = asyncio.get_event_loop()
        self._callbacks[symbol] = callback
        if self._watchdog_task is None:
            self._last_message = time.monotonic()
            self._watchdog_task = asyncio.create_task(self._watchdog())
        await asyncio.to_thread(self._subscribe_sync, symbol)
        logger.info(f"[bybit] subscribed to {symbol}")

    def _on_message(self, symbol: str):
        def on_message(message):
            self._last_message = time.monotonic()
            asyncio.run_coroutine_threadsafe(
                self._handle(symbol, message), self._loop
            )
        return on_message

    def _subscribe_sync(self, symbol: str) -> None:
        with self._ws_lock:
            self._ensure_ws()
            try:
                self._ws.ticker_stream(symbol=symbol, callback=self._on_message(symbol))
            except Exception as e:
                # pybit's callback_directory survives a WS reconnect (network
                # blip, exchange-side drop) even though the underlying
                # subscription on the exchange side may not — so a routine
                # reconnect makes every future subscribe() to an
                # already-registered topic raise "already subscribed", even
                # when ticks for that symbol have actually stopped flowing.
                # Rebuilding the socket clears pybit's internal state and
                # re-establishes every live subscription, restoring ticks for
                # ALL symbols on this stream — not just the one that triggered
                # this call — which is what actually happened in production:
                # one stale-subscription error here silently stalled price
                # delivery for every bot on this exchange.
                if "already subscribed" in str(e).lower():
                    logger.warning(
                        f"[bybit] stale subscription detected for {symbol} "
                        f"({e}) — reconnecting WebSocket to recover all symbols"
                    )
                    # _reconnect поднимает все символы из _callbacks, включая этот
                    self._reconnect()
                    return
                else:
                    raise

            self._subscribed.add(symbol)

    async def _watchdog(self):
        """pybit сдаётся после 10 неудачных переподключений (например, пропал
        DNS) и дальше молчит, а трекер продолжает считать символы подписанными.
        Если сообщений нет дольше STALE_AFTER — пересоздаём сокет; при неудаче
        пробуем снова на следующем круге.
        """
        while True:
            await asyncio.sleep(self.WATCHDOG_INTERVAL)
            if not self._callbacks:
                continue
            silence = time.monotonic() - self._last_message
            if silence < self.STALE_AFTER:
                continue
            logger.warning(
                f"[bybit] no messages for {silence:.0f}s — reconnecting WebSocket"
            )
            try:
                await asyncio.to_thread(self._locked_reconnect)
                self._last_message = time.monotonic()
            except Exception as e:
                logger.error(f"[bybit] reconnect failed, will retry: {e}")

    def _locked_reconnect(self):
        with self._ws_lock:
            self._reconnect()

    def _reconnect(self):
        """Tear down and rebuild the WS connection, then resubscribe every
        symbol that has a callback — clears pybit's stale callback_directory
        and re-registers real subscriptions for all of them, not just the one
        that surfaced the error. Symbols come from _callbacks, not _subscribed,
        so a failed rebuild doesn't lose them for the next attempt.
        """
        if self._ws:
            try:
                self._ws.exit()
            except Exception:
                pass
        self._ws = None
        self._subscribed.clear()

        self._ensure_ws()

        for sym in list(self._callbacks):
            try:
                self._ws.ticker_stream(symbol=sym, callback=self._on_message(sym))
                self._subscribed.add(sym)
            except Exception as e:
                logger.error(f"[bybit] failed to resubscribe {sym} after reconnect: {e}")

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
        if self._watchdog_task:
            self._watchdog_task.cancel()
            self._watchdog_task = None
        if self._ws:
            try:
                self._ws.exit()
            except Exception:
                pass
            self._ws = None
        self._subscribed.clear()
        self._callbacks.clear()
