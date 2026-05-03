from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Set
from app.services.bybit import bybit_client
from app.core.redis import get_live_price, set_live_price
from app.services.strategy import StrategyEngine
from app.core.database import AsyncSessionLocal
import json
import asyncio
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manage WebSocket connections"""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.price_subscribers: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket):
        """Accept new connection"""
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        """Remove connection"""
        self.active_connections.discard(websocket)

        # Remove from all subscriptions
        for symbol in list(self.price_subscribers.keys()):
            self.price_subscribers[symbol].discard(websocket)
            if not self.price_subscribers[symbol]:
                del self.price_subscribers[symbol]

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send message to specific client"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error sending message: {e}")

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        disconnected = set()

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast_price_update(self, symbol: str, price: float):
        """Broadcast price update to subscribers"""
        if symbol not in self.price_subscribers:
            return

        message = {
            "type": "price_update",
            "symbol": symbol,
            "price": price
        }

        disconnected = set()

        for connection in self.price_subscribers[symbol]:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)

        # Clean up
        for conn in disconnected:
            self.price_subscribers[symbol].discard(conn)

    async def broadcast_event(self, event_type: str, data: dict):
        """Broadcast trading events to all clients"""
        message = {
            "type": event_type,
            **data
        }

        disconnected = set()

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)

        # Clean up
        for conn in disconnected:
            self.disconnect(conn)

    def subscribe_to_price(self, symbol: str, websocket: WebSocket):
        """Subscribe client to price updates"""
        if symbol not in self.price_subscribers:
            self.price_subscribers[symbol] = set()

        self.price_subscribers[symbol].add(websocket)


# Global connection manager
manager = ConnectionManager()


class PriceStreamManager:
    """Manage price streams from Bybit"""

    def __init__(self):
        self.active_symbols: Set[str] = set()
        self.strategy_engines: Dict[int, StrategyEngine] = {}
        self.registered_bots: Set[int] = set()  # Track registered bot IDs

    async def start_price_stream(self, symbol: str):
        """Start streaming prices for a symbol"""
        if symbol in self.active_symbols:
            return

        self.active_symbols.add(symbol)

        # Получаем loop главного потока, чтобы передать его в колбэк pybit
        loop = asyncio.get_event_loop()

        def on_message(message):
            asyncio.run_coroutine_threadsafe(
                self._handle_price_update(symbol, message), loop
            )

        ws = bybit_client.init_websocket(on_message)
        bybit_client.subscribe_ticker(symbol, on_message)

        logger.info(f"Started price stream for {symbol}")

    async def _handle_price_update(self, symbol: str, message: dict):
        """Handle incoming price update"""
        try:
            if "data" in message:
                data = message["data"]
                price = float(data.get("lastPrice", 0))

                if price > 0:
                    await set_live_price(symbol, price)
                    await manager.broadcast_price_update(symbol, price)
                    await self._update_strategies(symbol, price)

        except Exception as e:
            logger.error(f"[WS] Ошибка обработки цены {symbol}: {e}", exc_info=True)

    async def _update_strategies(self, symbol: str, price: float):
        """Update all active strategies for this symbol"""
        # Create new DB session for each price update to avoid stale sessions
        for bot_id in list(self.registered_bots):
            if bot_id in self.strategy_engines:
                engine = self.strategy_engines[bot_id]
                if engine.bot.symbol == symbol:
                    try:
                        await engine.on_price_update(price)
                    except Exception as e:
                        logger.error(f"Error updating strategy {bot_id}: {e}")

    async def register_strategy(self, bot_id: int):
        """Register a strategy engine for price updates"""
        async with AsyncSessionLocal() as db:
            engine = StrategyEngine(bot_id, db)
            await engine.initialize()
            self.strategy_engines[bot_id] = engine
            self.registered_bots.add(bot_id)

            # Start price stream for this symbol
            await self.start_price_stream(engine.bot.symbol)

            logger.info(f"Registered strategy for bot {bot_id}, symbol: {engine.bot.symbol}")

    def unregister_strategy(self, bot_id: int):
        """Unregister strategy engine"""
        if bot_id in self.strategy_engines:
            del self.strategy_engines[bot_id]
        if bot_id in self.registered_bots:
            self.registered_bots.discard(bot_id)
        logger.info(f"Unregistered strategy for bot {bot_id}")

    async def restore_active_strategies(self):
        """
        Restore active strategies on application startup.

        This finds all bots in PYRAMIDING state with open positions
        and registers them for price updates.
        """
        try:
            async with AsyncSessionLocal() as db:
                from app.models import Bot, Position
                from sqlalchemy import select, and_

                # Find all bots in PYRAMIDING state with open positions
                result = await db.execute(
                    select(Bot)
                    .join(Position, Position.bot_id == Bot.id)
                    .where(
                        and_(
                            Bot.state == "PYRAMIDING",
                            Position.is_open == True
                        )
                    )
                )
                active_bots = result.scalars().all()

                logger.info(f"Restoring {len(active_bots)} active strategies on startup")

                for bot in active_bots:
                    try:
                        await self.register_strategy(bot.id)
                        logger.info(f"Restored strategy for bot {bot.id} ({bot.name})")
                    except Exception as e:
                        logger.error(f"Failed to restore strategy for bot {bot.id}: {e}")

                logger.info(f"Strategy restoration complete: {len(self.registered_bots)} bots registered")

        except Exception as e:
            logger.error(f"Error restoring active strategies: {e}")


# Global price stream manager
price_stream_manager = PriceStreamManager()
