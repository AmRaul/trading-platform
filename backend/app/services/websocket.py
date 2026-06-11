from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Set
from app.core.redis import get_redis, price_channel
from app.services.strategy import StrategyEngine
from app.core.database import AsyncSessionLocal
import json
import asyncio
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manage WebSocket connections from browser clients."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.price_subscribers: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
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
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)
        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast_price_update(self, symbol: str, price: float):
        if symbol not in self.price_subscribers:
            return
        message = {"type": "price_update", "symbol": symbol, "price": price}
        disconnected = set()
        for connection in self.price_subscribers[symbol]:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)
        for conn in disconnected:
            self.price_subscribers[symbol].discard(conn)

    async def broadcast_event(self, event_type: str, data: dict):
        message = {"type": event_type, **data}
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)
        for conn in disconnected:
            self.disconnect(conn)

    def subscribe_to_price(self, symbol: str, websocket: WebSocket):
        if symbol not in self.price_subscribers:
            self.price_subscribers[symbol] = set()
        self.price_subscribers[symbol].add(websocket)


manager = ConnectionManager()


class PriceStreamManager:
    """
    Listens to Redis pub/sub price channels published by price-tracker service.
    Drives strategy engines and broadcasts prices to browser WebSocket clients.

    Channel format: prices:{exchange}:{symbol}
    Adding a new exchange requires no changes here — price-tracker registers it.
    """

    def __init__(self):
        self.strategy_engines: Dict[int, StrategyEngine] = {}
        self.registered_bots: Set[int] = set()
        # symbol -> set of (exchange, symbol) channels being listened to
        self._listened_channels: Set[str] = set()
        self._pubsub_task: asyncio.Task | None = None
        self._pubsub = None

    async def _ensure_listener(self):
        if self._pubsub_task and not self._pubsub_task.done():
            return
        self._pubsub_task = asyncio.create_task(self._listen_loop())

    async def _listen_loop(self):
        redis = await get_redis()
        self._pubsub = redis.pubsub()
        if self._listened_channels:
            await self._pubsub.subscribe(*self._listened_channels)
        logger.info(f"[PriceStream] Redis pub/sub listener started, channels: {self._listened_channels}")
        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    exchange = data["exchange"]
                    symbol = data["symbol"]
                    price = float(data["price"])
                    await manager.broadcast_price_update(symbol, price)
                    await self._update_strategies(symbol, price)
                except Exception as e:
                    logger.error(f"[PriceStream] message error: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[PriceStream] listener crashed: {e}", exc_info=True)
        finally:
            if self._pubsub:
                await self._pubsub.close()

    async def _subscribe_channel(self, exchange: str, symbol: str):
        channel = price_channel(exchange, symbol)
        if channel in self._listened_channels:
            return
        self._listened_channels.add(channel)
        if self._pubsub:
            await self._pubsub.subscribe(channel)
        await self._ensure_listener()

    async def _update_strategies(self, symbol: str, price: float):
        for bot_id in list(self.registered_bots):
            engine = self.strategy_engines.get(bot_id)
            if engine and engine.bot.symbol == symbol:
                try:
                    await engine.on_price_update(price)
                except Exception as e:
                    logger.error(f"[PriceStream] strategy {bot_id} error: {e}")

    async def register_strategy(self, bot_id: int):
        db = AsyncSessionLocal()
        engine = StrategyEngine(bot_id, db)
        await engine.initialize()
        self.strategy_engines[bot_id] = engine
        self.registered_bots.add(bot_id)

        # Subscribe to price channel for this bot's exchange (default: bybit)
        exchange = getattr(engine.bot, "exchange", "bybit") or "bybit"
        await self._subscribe_channel(exchange, engine.bot.symbol)

        # Tell price-tracker to start streaming this symbol
        await _notify_price_tracker("subscribe", exchange, engine.bot.symbol)

        logger.info(f"[PriceStream] Registered bot {bot_id} {engine.bot.symbol} via {exchange}")

    def unregister_strategy(self, bot_id: int):
        engine = self.strategy_engines.pop(bot_id, None)
        if engine:
            asyncio.create_task(engine.db.close())
            # Notify price-tracker to stop streaming if no other bot needs this symbol
            exchange = getattr(engine.bot, "exchange", "bybit") or "bybit"
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
                result = await db.execute(
                    select(Bot)
                    .join(Position, Position.bot_id == Bot.id)
                    .where(and_(Bot.state == "PYRAMIDING", Position.is_open == True))
                )
                active_bots = result.scalars().all()
                logger.info(f"[PriceStream] Restoring {len(active_bots)} strategies")
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


async def _notify_price_tracker(action: str, exchange: str, symbol: str):
    """Call price-tracker HTTP API to subscribe/unsubscribe a symbol."""
    import aiohttp
    from app.core.config import settings
    url = f"{settings.PRICE_TRACKER_URL}/{action}"
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
