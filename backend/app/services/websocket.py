from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Optional, Set
from sqlalchemy import select
from app.core.redis import get_redis, price_channel
from app.services.strategy import StrategyEngine
from app.core.database import AsyncSessionLocal
import json
import time
import asyncio
import logging

logger = logging.getLogger(__name__)

RECONNECT_MIN_DELAY = 1
RECONNECT_MAX_DELAY = 30
# Отправка одному браузеру дольше этого — вкладка зависла или сеть умерла: отключаем,
# иначе одна такая вкладка тормозит рассылку всем (и раньше — раздачу цен ботам)
SEND_TIMEOUT_SEC = 2.0


async def _send_all(connections, message: dict) -> set:
    """Параллельная отправка с таймаутом. Возвращает подключения, которые надо снять."""
    connections = list(connections)
    if not connections:
        return set()

    async def one(conn):
        await asyncio.wait_for(conn.send_json(message), SEND_TIMEOUT_SEC)

    results = await asyncio.gather(*(one(c) for c in connections), return_exceptions=True)
    return {c for c, r in zip(connections, results) if isinstance(r, BaseException)}


class ConnectionManager:
    """Manage WebSocket connections from browser clients.

    Подключение принимается только после авторизации (routes/websocket.py), и у каждого
    известен пользователь. События бота (bot_id в данных) уходят только его владельцу.
    """

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.price_subscribers: Dict[str, Set[WebSocket]] = {}
        self.users: Dict[WebSocket, int] = {}
        self.bot_owner: Dict[int, int] = {}  # бот не меняет владельца — кешируем навсегда

    async def connect(self, websocket: WebSocket, user_id: int):
        """Регистрирует уже принятое и авторизованное подключение."""
        self.active_connections.add(websocket)
        self.users[websocket] = user_id

    async def owner_of(self, bot_id) -> Optional[int]:
        if bot_id is None:
            return None
        try:
            bot_id = int(bot_id)
        except (TypeError, ValueError):
            return None
        if bot_id not in self.bot_owner:
            from app.models import Bot
            async with AsyncSessionLocal() as db:
                uid = (await db.execute(select(Bot.user_id).where(Bot.id == bot_id))).scalar_one_or_none()
            if uid is None:
                return None
            self.bot_owner[bot_id] = uid
        return self.bot_owner[bot_id]

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        self.users.pop(websocket, None)
        for symbol in list(self.price_subscribers.keys()):
            self.price_subscribers[symbol].discard(websocket)
            if not self.price_subscribers[symbol]:
                del self.price_subscribers[symbol]

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error sending message: {e}")

    async def broadcast(self, message: dict):
        for conn in await _send_all(self.active_connections, message):
            self.disconnect(conn)

    async def broadcast_price_update(self, symbol: str, price: float):
        if symbol not in self.price_subscribers:
            return
        message = {"type": "price_update", "symbol": symbol, "price": price}
        for conn in await _send_all(self.price_subscribers[symbol], message):
            self.price_subscribers[symbol].discard(conn)

    async def broadcast_event(self, event_type: str, data: dict):
        """Событие бота — только подключениям его владельца; без bot_id / неизвестный бот — никому."""
        message = {"type": event_type, **data}
        owner = await self.owner_of(data.get("bot_id"))
        if owner is None:
            logger.debug(f"[WS] {event_type} без владельца — не рассылаем")
            return
        mine = [c for c in self.active_connections if self.users.get(c) == owner]
        for conn in await _send_all(mine, message):
            self.disconnect(conn)

    def subscribe_to_price(self, symbol: str, websocket: WebSocket):
        if symbol not in self.price_subscribers:
            self.price_subscribers[symbol] = set()
        self.price_subscribers[symbol].add(websocket)


manager = ConnectionManager()


class EngineWorker:
    """Свой цикл обработки цен у каждого бота.

    Раньше слушатель Redis вызывал on_price_update всех ботов по очереди: бот,
    ждущий биржу (webhook Cryptorg — до 30 с, подтверждение позиции — до 20 с),
    задерживал стопы всех остальных. Теперь слушатель только кладёт цену в ящик,
    а обрабатывает её задача бота. Ящик на одну цену: пока бот занят, промежуточные
    тики заменяются последним — проверять стоп по устаревшей цене бессмысленно.
    """

    def __init__(self, bot_id: int, engine: "StrategyEngine"):
        self.bot_id = bot_id
        self.engine = engine
        self._price: Optional[float] = None
        self._event = asyncio.Event()
        self._stopped = False
        self.task = asyncio.create_task(self._run())

    def push(self, price: float) -> None:
        self._price = price
        self._event.set()

    async def _run(self) -> None:
        while not self._stopped:
            await self._event.wait()
            self._event.clear()
            if self._stopped or self._price is None:
                continue
            try:
                await self.engine.on_price_update(self._price)
            except Exception as e:
                logger.error(f"[PriceStream] strategy {self.bot_id} error: {e}", exc_info=True)

    def stop(self) -> None:
        self._stopped = True
        self._event.set()
        # Бот снимает себя сам из своей же задачи (закрыл позицию) — не отменяем её
        # посреди операции: цикл выйдет сам после текущего тика.
        if asyncio.current_task() is not self.task:
            self.task.cancel()


class PriceStreamManager:
    """
    Listens to Redis pub/sub price channels published by price-tracker service.
    Drives strategy engines and broadcasts prices to browser WebSocket clients.

    Channel format: prices:{exchange}:{symbol}
    Adding a new exchange requires no changes here — price-tracker registers it.
    """

    def __init__(self):
        self.strategy_engines: Dict[int, StrategyEngine] = {}
        self.workers: Dict[int, EngineWorker] = {}
        self.registered_bots: Set[int] = set()
        # symbol -> время последнего тика из Redis, мс — для bots-health («идут ли цены»)
        self.last_tick_ms: Dict[str, int] = {}
        # symbol -> set of (exchange, symbol) channels being listened to
        self._listened_channels: Set[str] = set()
        self._pubsub_task: asyncio.Task | None = None
        self._pubsub = None

    @property
    def listener_alive(self) -> bool:
        """Слушатель Redis работает, если ему есть на что подписываться. Без каналов
        (нет ботов в позиции) его и не должно быть — это не поломка."""
        if not self._listened_channels:
            return True
        return bool(self._pubsub_task and not self._pubsub_task.done())

    async def _ensure_listener(self):
        if self._pubsub_task and not self._pubsub_task.done():
            return
        self._pubsub_task = asyncio.create_task(self._listen_loop())

    async def _listen_loop(self):
        """Читает цены из Redis pub/sub. При обрыве (Redis упал/перезапущен)
        переподключается с нарастающей паузой и заново подписывается на все
        каналы — иначе боты остаются без тиков до рестарта бэкенда."""
        delay = RECONNECT_MIN_DELAY
        while self._listened_channels:
            try:
                redis = await get_redis()
                self._pubsub = redis.pubsub()
                if self._listened_channels:
                    await self._pubsub.subscribe(*self._listened_channels)
                logger.info(f"[PriceStream] Redis pub/sub listener started, channels: {self._listened_channels}")
                delay = RECONNECT_MIN_DELAY
                async for message in self._pubsub.listen():
                    if message["type"] != "message":
                        continue
                    try:
                        data = json.loads(message["data"])
                        symbol = data["symbol"]
                        price = float(data["price"])
                        self.last_tick_ms[symbol] = int(time.time() * 1000)
                        # сначала боты (без ожидания — см. EngineWorker), потом браузеры
                        await self._update_strategies(symbol, price)
                        await manager.broadcast_price_update(symbol, price)
                    except Exception as e:
                        logger.error(f"[PriceStream] message error: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[PriceStream] listener lost Redis: {e} — reconnect in {delay}s")
            finally:
                await self._close_pubsub()
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_DELAY)

    async def _close_pubsub(self):
        pubsub, self._pubsub = self._pubsub, None
        if pubsub:
            try:
                await pubsub.close()
            except Exception:
                pass

    async def _subscribe_channel(self, exchange: str, symbol: str):
        channel = price_channel(exchange, symbol)
        if channel in self._listened_channels:
            return
        self._listened_channels.add(channel)
        if self._pubsub:
            try:
                await self._pubsub.subscribe(channel)
            except Exception as e:
                # Канал уже в _listened_channels — подпишемся при переподключении
                logger.warning(f"[PriceStream] subscribe {channel} failed: {e}")
        await self._ensure_listener()

    async def start_price_stream(self, symbol: str, exchange: str = "bybit"):
        """Subscribe to a symbol's price channel for browser-only display —
        used by the /ws subscribe_price message (positions page price
        ticker), independent of whether any bot is trading that symbol.
        Defaults to bybit, same as register_strategy's fallback.
        """
        await self._subscribe_channel(exchange, symbol)
        await _notify_price_tracker("subscribe", exchange, symbol)

    async def _update_strategies(self, symbol: str, price: float):
        """Раздать цену ботам монеты. Не ждёт их обработки — см. EngineWorker."""
        for bot_id in list(self.registered_bots):
            engine = self.strategy_engines.get(bot_id)
            worker = self.workers.get(bot_id)
            if engine and worker and engine.bot.symbol == symbol:
                worker.push(price)

    async def register_strategy(self, bot_id: int):
        # без сессии: движок открывает её сам на каждую операцию с БД
        engine = StrategyEngine(bot_id)
        await engine.initialize()
        old = self.workers.pop(bot_id, None)
        if old:
            old.stop()
        self.strategy_engines[bot_id] = engine
        self.workers[bot_id] = EngineWorker(bot_id, engine)
        self.registered_bots.add(bot_id)

        # Subscribe to price channel for this bot's price feed
        exchange = _price_feed(engine.bot)
        await self._subscribe_channel(exchange, engine.bot.symbol)

        # Tell price-tracker to start streaming this symbol
        await _notify_price_tracker("subscribe", exchange, engine.bot.symbol)

        logger.info(f"[PriceStream] Registered bot {bot_id} {engine.bot.symbol} via {exchange}")

    def unregister_strategy(self, bot_id: int):
        worker = self.workers.pop(bot_id, None)
        if worker:
            worker.stop()
        engine = self.strategy_engines.pop(bot_id, None)
        if engine:
            # Notify price-tracker to stop streaming if no other bot needs this symbol
            exchange = _price_feed(engine.bot)
            symbol = engine.bot.symbol
            still_needed = any(
                e.bot.symbol == symbol
                for e in self.strategy_engines.values()
            )
            if not still_needed:
                asyncio.create_task(
                    _notify_price_tracker("unsubscribe", exchange, symbol)
                )
        self.registered_bots.discard(bot_id)
        logger.info(f"[PriceStream] Unregistered bot {bot_id}")

    async def restore_active_strategies(self):
        try:
            async with AsyncSessionLocal() as db:
                from app.models import Bot, Position
                from sqlalchemy import select, and_

                pyramiding_result = await db.execute(
                    select(Bot)
                    .join(Position, Position.bot_id == Bot.id)
                    .where(and_(Bot.state == "PYRAMIDING", Position.is_open == True))
                )
                pyramiding_bots = pyramiding_result.scalars().all()

                # WAITING bots have no Position yet (still waiting for their
                # limit_entry_price to be hit) — no join needed, and joining
                # here would silently drop them since they have no row in
                # positions. Without this, a WAITING bot never gets
                # re-subscribed to price ticks after a backend restart, so
                # its limit order never triggers even if price already
                # crossed it hours ago.
                waiting_result = await db.execute(
                    select(Bot).where(Bot.state == "WAITING")
                )
                waiting_bots = waiting_result.scalars().all()

                # Straddle может ждать хода без открытой позиции — состояние в Bot.runtime_state
                straddle_result = await db.execute(
                    select(Bot).where(Bot.state == "STRADDLE")
                )
                straddle_bots = straddle_result.scalars().all()

                active_bots = list(pyramiding_bots) + list(waiting_bots) + list(straddle_bots)
                logger.info(
                    f"[PriceStream] Restoring {len(pyramiding_bots)} pyramiding + "
                    f"{len(waiting_bots)} waiting + {len(straddle_bots)} straddle strategies"
                )
                for bot in active_bots:
                    try:
                        await self.register_strategy(bot.id)
                    except Exception as e:
                        logger.error(f"[PriceStream] Failed to restore bot {bot.id}: {e}")
        except Exception as e:
            logger.error(f"[PriceStream] restore error: {e}")

    async def stop(self):
        if self._pubsub_task:
            self._pubsub_task.cancel()
        for worker in list(self.workers.values()):
            worker.stop()
        self.workers.clear()


def _price_feed(bot) -> str:
    """Биржа, с которой берём цену. bot.exchange — это площадка исполнения:
    у Cryptorg своей ленты нет, а price-tracker знает только bybit,
    поэтому всё, что не bybit, слушаем через bybit.
    """
    return "bybit"


async def _notify_price_tracker(action: str, exchange: str, symbol: str):
    """Call price-tracker HTTP API to subscribe/unsubscribe a symbol."""
    import aiohttp
    from app.core.config import settings
    url = f"{settings.PRICE_TRACKER_URL}/subscribe"
    try:
        async with aiohttp.ClientSession() as session:
            if action == "subscribe":
                async with session.post(url, json={"exchange": exchange, "symbol": symbol}) as r:
                    if r.status != 200:
                        logger.warning(f"[PriceTracker] subscribe {symbol} status {r.status}")
            else:
                async with session.delete(url, json={"exchange": exchange, "symbol": symbol}) as r:
                    if r.status != 200:
                        logger.warning(f"[PriceTracker] unsubscribe {symbol} status {r.status}")
    except Exception as e:
        logger.warning(f"[PriceTracker] notify failed ({action} {symbol}): {e}")


price_stream_manager = PriceStreamManager()
