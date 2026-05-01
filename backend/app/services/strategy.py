from enum import Enum
from typing import Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Bot, Position, Order, Trade
from app.services.position_manager import PositionManager, OrderInfo
from app.services.bybit import bybit_client  # For price data
from app.services.cryptorg import cryptorg_client  # For trading
from app.core.redis import set_position_state, get_position_state, delete_position_state
from datetime import datetime
from sqlalchemy import select
import logging

logger = logging.getLogger(__name__)

# Import manager for WebSocket events (avoid circular import)
_ws_manager = None

def get_ws_manager():
    """Lazy import to avoid circular dependency"""
    global _ws_manager
    if _ws_manager is None:
        from app.services.websocket import manager
        _ws_manager = manager
    return _ws_manager


class BotState(str, Enum):
    """Bot state machine"""
    IDLE = "IDLE"
    ENTRY = "ENTRY"
    PYRAMIDING = "PYRAMIDING"
    EXIT = "EXIT"


class StrategyEngine:
    """Main strategy execution engine"""

    def __init__(self, bot_id: int, db: AsyncSession):
        self.bot_id = bot_id
        self.db = db
        self.bot: Optional[Bot] = None
        self.position: Optional[Position] = None
        self.position_manager: Optional[PositionManager] = None
        self.current_state = BotState.IDLE

    async def initialize(self):
        """Load bot and position from database"""
        # Load bot
        result = await self.db.execute(select(Bot).where(Bot.id == self.bot_id))
        self.bot = result.scalar_one_or_none()

        if not self.bot:
            raise ValueError(f"Bot {self.bot_id} not found")

        # Load active position
        result = await self.db.execute(
            select(Position).where(
                Position.bot_id == self.bot_id,
                Position.is_open == True
            )
        )
        self.position = result.scalar_one_or_none()

        # Initialize position manager
        self.position_manager = PositionManager(self.bot.config)

        # Restore state from Redis or database
        await self._restore_state()

        self.current_state = BotState(self.bot.state)

    async def _restore_state(self):
        """Restore position manager state from database"""
        if not self.position:
            return

        # Load all orders for this position
        result = await self.db.execute(
            select(Order)
            .where(Order.position_id == self.position.id)
            .where(Order.status == "FILLED")
            .order_by(Order.order_number)
        )
        orders = result.scalars().all()

        # Restore orders in position manager
        for order in orders:
            order_info = OrderInfo(
                order_number=order.order_number,
                price=order.price,
                size=order.size
            )
            self.position_manager.add_order(order_info)

    async def manual_entry(self, account_balance: float = None) -> Dict:
        """
        Manual entry trigger (called from UI)

        Args:
            account_balance: Not used anymore, kept for compatibility
        """
        if self.current_state != BotState.IDLE:
            return {"success": False, "error": "Bot not in IDLE state"}

        try:
            # Calculate first order size in USDT
            order_size_usdt = self.position_manager.calculate_next_order_size()

            # Get current price from Bybit (for reference and record keeping)
            ticker = await bybit_client.get_ticker(self.bot.symbol)
            if not ticker:
                return {"success": False, "error": "Failed to get ticker price"}

            current_price = float(ticker["lastPrice"])

            # Place order on Cryptorg Ghost Bot (actual trading)
            order_result = await cryptorg_client.open_position(
                symbol=self.bot.symbol,
                side=self.bot.side.lower(),  # "long" or "short"
                order_volume_usdt=order_size_usdt,
                leverage=self.bot.config["leverage"]
            )

            if not order_result or not order_result.get("success"):
                return {"success": False, "error": order_result.get("error", "Failed to place order")}

            # Create position in database
            self.position = Position(
                bot_id=self.bot_id,
                symbol=self.bot.symbol,
                side=self.bot.side,
                total_size=order_size_usdt,
                average_price=current_price,
                order_count=1,
                is_open=True
            )
            self.db.add(self.position)
            await self.db.flush()

            # Create order record
            order = Order(
                position_id=self.position.id,
                bot_id=self.bot_id,
                exchange_order_id=order_result.get("orderId"),
                symbol=self.bot.symbol,
                side=self.bot.side.lower(),  # "long" or "short"
                size=order_size_usdt,
                price=current_price,
                order_number=1,
                status="FILLED",
                filled_at=datetime.utcnow()
            )
            self.db.add(order)

            # Update position manager
            self.position_manager.add_order(OrderInfo(1, current_price, order_size_usdt))

            # Calculate initial SL
            sl_price, sl_type = self.position_manager.calculate_stop_loss(
                self.bot.side,
                self.position_manager.orders,
                current_price
            )
            self.position.current_sl = sl_price

            # Set real stop-loss on exchange via Cryptorg
            sl_result = await cryptorg_client.set_stop_loss(
                symbol=self.bot.symbol,
                side=self.bot.side.lower(),
                stop_price=sl_price
            )

            if sl_result and sl_result.get("success"):
                logger.info(f"Stop-loss set on exchange: {sl_price}")
            else:
                logger.warning(f"Failed to set stop-loss on exchange, using software fallback only")

            # Update bot state
            self.bot.state = BotState.PYRAMIDING
            self.bot.started_at = datetime.utcnow()
            self.current_state = BotState.PYRAMIDING

            await self.db.commit()

            # Save state to Redis
            await self._save_state()

            # Register strategy for price updates
            from app.services.websocket import price_stream_manager
            await price_stream_manager.register_strategy(self.bot_id)

            logger.info(f"Manual entry executed for bot {self.bot_id}: {order_size_usdt} USDT @ {current_price}")

            return {
                "success": True,
                "order_id": order.id,
                "price": current_price,
                "size": order_size_usdt,
                "sl": sl_price
            }

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error in manual entry: {e}")
            return {"success": False, "error": str(e)}

    async def on_price_update(self, current_price: float):
        """
        Handle real-time price updates from Bybit WebSocket

        This is the main control loop for position management:
        1. Check if Stop Loss was hit → close position
        2. Check if we should add pyramiding order → add order
        3. Update position state (PnL, trailing SL) → broadcast to UI

        Called continuously from PriceStreamManager when new price arrives
        """
        if self.current_state not in [BotState.PYRAMIDING]:
            return

        if not self.position or not self.position.is_open:
            return

        try:
            # 1. Check if Stop Loss hit
            if self.position_manager.is_stop_loss_hit(
                self.bot.side,
                current_price,
                self.position.current_sl
            ):
                # Broadcast SL hit event to UI
                await get_ws_manager().broadcast_event("stop_loss_triggered", {
                    "bot_id": self.bot_id,
                    "symbol": self.bot.symbol,
                    "side": self.bot.side,
                    "price": current_price,
                    "sl_price": self.position.current_sl
                })
                await self._close_position(current_price, "SL_HIT")
                return

            # 2. Check if should add pyramiding order (averaging)
            last_order_price = self.position_manager.get_last_order_price()

            if self.position_manager.should_add_order(
                self.bot.side,
                current_price,
                last_order_price
            ):
                await self._add_pyramiding_order(current_price)
                return

            # 3. Update unrealized PnL and trailing SL
            await self._update_position_state(current_price)

        except Exception as e:
            logger.error(f"Error in price update handler: {e}")

    async def _add_pyramiding_order(self, current_price: float):
        """Add pyramiding order"""
        try:
            # Calculate order size in USDT
            order_size_usdt = self.position_manager.calculate_next_order_size()
            order_number = len(self.position_manager.orders) + 1

            # Place order on Cryptorg Ghost Bot (add to position)
            order_result = await cryptorg_client.add_to_position(
                symbol=self.bot.symbol,
                side=self.bot.side.lower(),  # "long" or "short"
                amount_usdt=order_size_usdt
            )

            if not order_result or not order_result.get("success"):
                logger.error("Failed to place pyramiding order")
                return

            # Create order record
            order = Order(
                position_id=self.position.id,
                bot_id=self.bot_id,
                exchange_order_id=order_result.get("orderId"),
                symbol=self.bot.symbol,
                side=self.bot.side.lower(),  # "long" or "short"
                size=order_size_usdt,
                price=current_price,
                order_number=order_number,
                status="FILLED",
                filled_at=datetime.utcnow()
            )
            self.db.add(order)

            # Update position manager
            self.position_manager.add_order(OrderInfo(order_number, current_price, order_size_usdt))

            # Recalculate average price and SL
            avg_price = self.position_manager.calculate_average_price(self.position_manager.orders)
            total_size = self.position_manager.get_total_size()

            sl_price, sl_type = self.position_manager.calculate_stop_loss(
                self.bot.side,
                self.position_manager.orders,
                current_price
            )

            # Update position
            self.position.average_price = avg_price
            self.position.total_size = total_size
            self.position.current_sl = sl_price
            self.position.order_count = order_number

            # Update stop-loss on exchange
            sl_result = await cryptorg_client.set_stop_loss(
                symbol=self.bot.symbol,
                side=self.bot.side.lower(),
                stop_price=sl_price
            )

            if sl_result and sl_result.get("success"):
                logger.info(f"Stop-loss updated on exchange: {sl_price}")
            else:
                logger.warning(f"Failed to update stop-loss on exchange")

            await self.db.commit()
            await self._save_state()

            logger.info(f"Pyramiding order added: #{order_number} @ {current_price}, new avg: {avg_price}, new SL: {sl_price}")

            # Broadcast pyramiding event to UI
            await get_ws_manager().broadcast_event("pyramiding_order_added", {
                "bot_id": self.bot_id,
                "symbol": self.bot.symbol,
                "side": self.bot.side,
                "order_number": order_number,
                "price": current_price,
                "size": order_size_usdt,
                "new_average_price": avg_price,
                "new_sl": sl_price,
                "total_size": total_size
            })

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error adding pyramiding order: {e}")

    async def _close_position(self, exit_price: float, exit_reason: str):
        """Close position"""
        try:
            # Close position on Cryptorg
            close_result = await cryptorg_client.close_position(
                symbol=self.bot.symbol,
                side=self.bot.side,
                quantity=self.position.total_size
            )

            if not close_result or not close_result.get("success"):
                logger.error("Failed to close position on Cryptorg")
                # Still close in our system
                pass

            # Calculate final PnL
            pnl = self.position_manager.calculate_unrealized_pnl(
                self.bot.side,
                self.position.average_price,
                exit_price,
                self.position.total_size
            )

            pnl_percent = self.position_manager.calculate_pnl_percent(
                self.bot.side,
                self.position.average_price,
                exit_price
            )

            # Create trade record
            first_order = self.position_manager.orders[0]
            trade = Trade(
                bot_id=self.bot_id,
                position_id=self.position.id,
                symbol=self.bot.symbol,
                side=self.bot.side,
                entry_price=first_order.price,
                average_price=self.position.average_price,
                total_size=self.position.total_size,
                exit_price=exit_price,
                exit_reason=exit_reason,
                pnl=pnl,
                pnl_percent=pnl_percent,
                total_orders=self.position.order_count,
                opened_at=self.position.opened_at
            )
            self.db.add(trade)

            # Update position
            self.position.is_open = False
            self.position.closed_at = datetime.utcnow()
            self.position.realized_pnl = pnl

            # Update bot
            self.bot.state = BotState.IDLE
            self.bot.total_pnl += pnl
            self.bot.stopped_at = datetime.utcnow()
            self.current_state = BotState.IDLE

            await self.db.commit()

            # Clear Redis state
            await delete_position_state(str(self.bot_id))

            # Unregister strategy from price updates
            from app.services.websocket import price_stream_manager
            price_stream_manager.unregister_strategy(self.bot_id)

            total_orders = self.position.order_count
            closed_avg_price = self.position.average_price

            # Reset position manager
            self.position_manager.reset()
            self.position = None

            logger.info(f"Position closed: {exit_reason}, PnL: {pnl:.2f} ({pnl_percent:.2f}%)")

            # Broadcast position closed event to UI
            await get_ws_manager().broadcast_event("position_closed", {
                "bot_id": self.bot_id,
                "symbol": self.bot.symbol,
                "side": self.bot.side,
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "pnl": pnl,
                "pnl_percent": pnl_percent,
                "total_orders": total_orders,
                "entry_price": first_order.price,
                "average_price": closed_avg_price
            })

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error closing position: {e}")

    async def _update_position_state(self, current_price: float):
        """
        Update position state (PnL, trailing SL)

        Trailing Stop Logic:
        - Calculates both dynamic SL (from avg price) and trailing SL (from current price)
        - Uses the better one (closer to profit)
        - SL only moves in profitable direction:
          * LONG: SL can only increase (move up)
          * SHORT: SL can only decrease (move down)
        """
        # Calculate unrealized PnL
        pnl = self.position_manager.calculate_unrealized_pnl(
            self.bot.side,
            self.position.average_price,
            current_price,
            self.position.total_size
        )

        # Calculate new SL (includes trailing logic if enabled)
        sl_price, sl_type = self.position_manager.calculate_stop_loss(
            self.bot.side,
            self.position_manager.orders,
            current_price
        )

        # Only move SL in profitable direction
        # LONG: SL can only increase (move up to protect profit)
        # SHORT: SL can only decrease (move down to protect profit)
        old_sl = self.position.current_sl
        sl_moved = False

        if self.bot.side == "LONG":
            if sl_price > self.position.current_sl:
                self.position.current_sl = sl_price
                sl_moved = True
        else:  # SHORT
            if sl_price < self.position.current_sl:
                self.position.current_sl = sl_price
                sl_moved = True

        # Log and broadcast trailing SL movements
        if sl_moved:
            logger.info(f"Trailing SL moved: {old_sl:.2f} → {sl_price:.2f} (type: {sl_type})")

            # Update stop-loss on exchange
            sl_result = await cryptorg_client.set_stop_loss(
                symbol=self.bot.symbol,
                side=self.bot.side.lower(),
                stop_price=sl_price
            )

            if sl_result and sl_result.get("success"):
                logger.info(f"Trailing stop-loss updated on exchange: {sl_price}")
            else:
                logger.warning(f"Failed to update trailing stop-loss on exchange")

            # Broadcast trailing SL event to UI
            await get_ws_manager().broadcast_event("trailing_stop_moved", {
                "bot_id": self.bot_id,
                "symbol": self.bot.symbol,
                "side": self.bot.side,
                "old_sl": old_sl,
                "new_sl": sl_price,
                "sl_type": sl_type,
                "current_price": current_price,
                "unrealized_pnl": pnl
            })

        self.position.unrealized_pnl = pnl

        # Save to Redis for fast access
        await self._save_state()

    async def _save_state(self):
        """Save position state to Redis"""
        if not self.position:
            return

        state = {
            "bot_id": self.bot_id,
            "position_id": self.position.id,
            "symbol": self.bot.symbol,
            "side": self.bot.side,
            "average_price": self.position.average_price,
            "total_size": self.position.total_size,
            "current_sl": self.position.current_sl,
            "unrealized_pnl": self.position.unrealized_pnl,
            "order_count": self.position.order_count,
            "state": self.current_state
        }
        await set_position_state(str(self.bot_id), state)

    async def manual_close(self) -> Dict:
        """Manual close position (called from UI)"""
        if not self.position or not self.position.is_open:
            return {"success": False, "error": "No open position"}

        try:
            # Get current price
            ticker = await bybit_client.get_ticker(self.bot.symbol)
            if not ticker:
                return {"success": False, "error": "Failed to get ticker price"}

            current_price = float(ticker["lastPrice"])

            # Close position
            await self._close_position(current_price, "MANUAL_CLOSE")

            return {"success": True, "exit_price": current_price}

        except Exception as e:
            logger.error(f"Error in manual close: {e}")
            return {"success": False, "error": str(e)}
