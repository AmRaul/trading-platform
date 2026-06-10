from enum import Enum
from typing import Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import Bot, Position, Order
from app.models.user_credential import UserCredential
from app.domain.trading.entities import OrderInfo
from app.domain.trading.position_calculator import PositionCalculator
from app.adapters.cryptorg_executor import CryptorgExecutorAdapter
from app.adapters.bybit_market_data import BybitMarketDataAdapter
from app.adapters.websocket_publisher import WebSocketPublisherAdapter
from app.application.trading.open_position import OpenPositionUseCase
from app.application.trading.close_position import ClosePositionUseCase
from app.application.trading.add_pyramiding_order import AddPyramidingOrderUseCase
from app.application.trading.handle_price_update import HandlePriceUpdateUseCase
from app.services.cryptorg import get_cryptorg_client
import logging
import time

logger = logging.getLogger(__name__)


class BotState(str, Enum):
    IDLE = "IDLE"
    ENTRY = "ENTRY"
    PYRAMIDING = "PYRAMIDING"
    EXIT = "EXIT"


class StrategyEngine:
    """Thin orchestrator — delegates all logic to use cases."""

    def __init__(self, bot_id: int, db: AsyncSession):
        self.bot_id = bot_id
        self.db = db
        self.bot: Optional[Bot] = None
        self.position: Optional[Position] = None
        self.calculator: Optional[PositionCalculator] = None
        self.current_state = BotState.IDLE
        self._is_adding_order = False
        self._is_closing = False
        self._last_tick_log = 0.0

        self._market = BybitMarketDataAdapter()
        self._publisher = WebSocketPublisherAdapter()

    async def initialize(self):
        result = await self.db.execute(select(Bot).where(Bot.id == self.bot_id))
        self.bot = result.scalar_one_or_none()
        if not self.bot:
            raise ValueError(f"Bot {self.bot_id} not found")

        # Load user credential and build executor with the correct webhook URL
        credential = None
        if self.bot.user_id:
            cred_result = await self.db.execute(
                select(UserCredential).where(UserCredential.user_id == self.bot.user_id)
            )
            credential = cred_result.scalar_one_or_none()

        executor = CryptorgExecutorAdapter(get_cryptorg_client(credential))

        self._open_uc = OpenPositionUseCase(executor, self._market, self._publisher)
        self._close_uc = ClosePositionUseCase(executor, self._publisher)
        self._add_order_uc = AddPyramidingOrderUseCase(executor, self._market, self._publisher)
        self._price_update_uc = HandlePriceUpdateUseCase(self._publisher)

        result = await self.db.execute(
            select(Position).where(Position.bot_id == self.bot_id, Position.is_open == True)
        )
        self.position = result.scalar_one_or_none()

        self.calculator = PositionCalculator(self.bot.config)
        await self._restore_state()
        self.current_state = BotState(self.bot.state)

    async def _restore_state(self):
        if not self.position:
            return
        result = await self.db.execute(
            select(Order)
            .where(Order.position_id == self.position.id, Order.status == "FILLED")
            .order_by(Order.order_number)
        )
        for order in result.scalars().all():
            self.calculator.add_order(OrderInfo(order.order_number, order.price, order.size))

    async def manual_entry(self, account_balance: float = None) -> Dict:
        if self.current_state != BotState.IDLE:
            return {"success": False, "error": "Bot not in IDLE state"}
        try:
            result = await self._open_uc.execute(self.bot, self.calculator, self.db)
            if result["success"]:
                self.position = result.pop("position")
                self.current_state = BotState.PYRAMIDING

                from app.services.websocket import price_stream_manager
                await price_stream_manager.register_strategy(self.bot_id)
            return result
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error in manual_entry: {e}")
            return {"success": False, "error": str(e)}

    async def on_price_update(self, current_price: float):
        if self.current_state != BotState.PYRAMIDING:
            return
        if not self.position or not self.position.is_open:
            return

        cfg = self.bot.config
        orders_count = len(self.calculator.orders)
        last_order_price = self.calculator.get_last_order_price()

        now = time.time()
        if now - self._last_tick_log >= 30:
            self._last_tick_log = now
            step = cfg.get("step_percent", "?")
            max_orders = cfg.get("order_count", "?")
            logger.info(
                f"[TICK] bot={self.bot_id} {self.bot.symbol} {self.bot.side} "
                f"price={current_price:.6f} avg={self.position.average_price:.6f} "
                f"sl={self.position.current_sl:.6f} orders={orders_count}/{max_orders} "
                f"last_order={last_order_price:.6f} step={step}% "
                f"pnl={self.position.unrealized_pnl:.4f} USDT"
            )

        try:
            if self._is_closing or not self.position or not self.position.is_open:
                return

            # 1. Check SL hit
            if self.calculator.is_stop_loss_hit(self.bot.side, current_price, self.position.current_sl):
                if self._is_closing:
                    return
                _, sl_type = self.calculator.calculate_stop_loss(
                    self.bot.side, self.calculator.orders, current_price
                )
                exit_reason = "TRAILING_STOP" if sl_type == "trailing" else "SL_HIT"
                logger.info(
                    f"[{exit_reason}] bot={self.bot_id} symbol={self.bot.symbol} "
                    f"current={current_price} sl={self.position.current_sl}"
                )
                await self._publisher.publish("stop_loss_triggered", {
                    "bot_id": self.bot_id,
                    "symbol": self.bot.symbol,
                    "side": self.bot.side,
                    "price": current_price,
                    "sl_price": self.position.current_sl,
                    "sl_type": sl_type,
                })
                await self._close_position(current_price, exit_reason)
                return

            # 2. Check add-order trigger
            # DCA bots: Cryptorg handles limit orders natively — no manual averaging needed
            bot_type = self.bot.config.get("bot_type", "pyramiding")
            if bot_type == "pyramiding":
                if self.calculator.should_add_order(self.bot.side, current_price, last_order_price):
                    if self._is_adding_order:
                        return
                    logger.info(
                        f"[AVG TRIGGER] bot={self.bot_id} current={current_price} "
                        f"last_order={last_order_price} orders={orders_count}"
                    )
                    await self._add_pyramiding_order(current_price)
                    return

            # 3. Update trailing SL + PnL
            await self._price_update_uc.execute(self.bot, self.position, self.calculator, current_price)

        except Exception as e:
            logger.error(f"[ERROR] on_price_update bot={self.bot_id}: {e}", exc_info=True)

    async def _add_pyramiding_order(self, current_price: float):
        self._is_adding_order = True
        try:
            result = await self._add_order_uc.execute(
                self.bot, self.position, self.calculator, current_price, self.db
            )
            if not result["success"]:
                logger.error(f"Pyramiding order failed: {result.get('error')}")
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error adding pyramiding order: {e}")
        finally:
            self._is_adding_order = False

    async def _close_position(self, exit_price: float, exit_reason: str):
        self._is_closing = True
        try:
            await self._close_uc.execute(
                self.bot, self.position, self.calculator, exit_price, exit_reason, self.db
            )
            self.current_state = BotState.IDLE
            self.position = None

            from app.services.websocket import price_stream_manager
            price_stream_manager.unregister_strategy(self.bot_id)
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error closing position: {e}")
        finally:
            self._is_closing = False

    async def manual_close(self) -> Dict:
        if self.bot.state == BotState.IDLE or not self.position or not self.position.is_open:
            return {"success": False, "error": "No open position"}
        try:
            from app.services.bybit import bybit_client
            ticker = await bybit_client.get_ticker(self.bot.symbol)
            if not ticker:
                return {"success": False, "error": "Failed to get ticker price"}
            current_price = float(ticker["lastPrice"])
            await self._close_position(current_price, "MANUAL_CLOSE")
            return {"success": True, "exit_price": current_price}
        except Exception as e:
            logger.error(f"Error in manual_close: {e}")
            return {"success": False, "error": str(e)}
