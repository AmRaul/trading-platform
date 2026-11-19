import functools
from contextlib import asynccontextmanager
from enum import Enum
from typing import Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, inspect as sa_inspect
from app.core.database import AsyncSessionLocal
from app.models import Bot, Position, Order
from app.domain.trading.entities import OrderInfo
from app.domain.trading.position_calculator import PositionCalculator
from app.adapters.bybit_market_data import BybitMarketDataAdapter
from app.adapters.executor_factory import build_executor
from app.adapters.websocket_publisher import WebSocketPublisherAdapter
from app.application.trading.open_position import OpenPositionUseCase
from app.application.trading.close_position import ClosePositionUseCase
from app.application.trading.add_pyramiding_order import AddPyramidingOrderUseCase
from app.application.trading.handle_price_update import HandlePriceUpdateUseCase
import logging
import time

logger = logging.getLogger(__name__)


# Как часто сверять открытую позицию с биржей (get_open_position_size)
RECONCILE_INTERVAL_SEC = 60


class BotState(str, Enum):
    IDLE = "IDLE"
    WAITING = "WAITING"
    SIGNAL = "SIGNAL"  # ждёт сигнал входа (config.entry_signal), проверяет SignalEntryScheduler
    ENTRY = "ENTRY"
    PYRAMIDING = "PYRAMIDING"
    EXIT = "EXIT"
    STRADDLE = "STRADDLE"  # конструкция straddle запущена (см. StraddleRunner)


def _in_session(fn):
    """Метод, которому нужна БД, получает сессию на время своей работы (см. StrategyEngine.session)."""
    @functools.wraps(fn)
    async def wrapper(self, *args, **kwargs):
        async with self.session():
            return await fn(self, *args, **kwargs)
    return wrapper


class StrategyEngine:
    """Thin orchestrator — delegates all logic to use cases.

    Сессия БД. Движок из API/планировщика получает сессию запроса (db=...) и живёт
    одну операцию. Движок зарегистрированного бота (price_stream_manager) живёт днями
    и сессию не держит: каждая операция с БД (вход, добор, закрытие, шаг straddle)
    открывает свою и прикрепляет к ней bot/position. Тик без событий БД не трогает —
    стоп и PnL меняются в памяти и уходят в базу со следующей операцией, как и раньше.
    После rollback объекты перечитываются из базы, а не остаются «протухшими».
    """

    straddle = None  # StraddleRunner для bot_type=straddle
    _fixed_db: Optional[AsyncSession] = None
    _op_db: Optional[AsyncSession] = None

    def __init__(self, bot_id: int, db: Optional[AsyncSession] = None):
        self.bot_id = bot_id
        self._fixed_db = db
        self._op_db = None
        self.bot: Optional[Bot] = None
        self.position: Optional[Position] = None
        self.calculator: Optional[PositionCalculator] = None
        self.current_state = BotState.IDLE
        self._is_adding_order = False
        self._is_closing = False
        self._is_entering = False
        self._last_tick_log = 0.0
        self._executor = None
        self._last_reconcile = time.time()

        self._market = BybitMarketDataAdapter()
        self._publisher = WebSocketPublisherAdapter()

    @property
    def db(self) -> AsyncSession:
        db = self._fixed_db or self._op_db
        if db is None:
            raise RuntimeError(f"bot={self.bot_id}: обращение к БД вне операции (нужен StrategyEngine.session)")
        return db

    @db.setter
    def db(self, value: AsyncSession) -> None:
        self._fixed_db = value

    def _tracked(self):
        objs = [self.bot, self.position]
        if self.straddle:
            objs.extend(self.straddle.positions.values())
        return [o for o in objs if o is not None]

    @asynccontextmanager
    async def session(self):
        """Сессия на одну операцию. Вложенные вызовы и движок с сессией запроса — та же сессия."""
        if self._fixed_db is not None or self._op_db is not None:
            yield self.db
            return
        async with AsyncSessionLocal() as db:
            for obj in self._tracked():
                db.add(obj)  # прикрепить; несохранённые изменения (стоп, PnL) уйдут при commit
            self._op_db = db
            try:
                yield db
            finally:
                try:
                    for obj in self._tracked():
                        state = sa_inspect(obj)
                        if state.session is db.sync_session and state.expired_attributes:
                            await db.refresh(obj)  # после rollback — состояние из базы
                except Exception as e:
                    logger.error(f"[SESSION] bot={self.bot_id} refresh after rollback failed: {e}")
                finally:
                    self._op_db = None

    @_in_session
    async def initialize(self):
        result = await self.db.execute(select(Bot).where(Bot.id == self.bot_id))
        self.bot = result.scalar_one_or_none()
        if not self.bot:
            raise ValueError(f"Bot {self.bot_id} not found")

        # OpenPositionUseCase/AddPyramidingOrderUseCase/ClosePositionUseCase
        # зависят только от порта ExchangeExecutor — адаптер выбирает фабрика.
        executor = await build_executor(self.bot, self.db)
        self._executor = executor
        self._open_uc = OpenPositionUseCase(executor, self._market, self._publisher)
        self._close_uc = ClosePositionUseCase(executor, self._publisher)
        self._add_order_uc = AddPyramidingOrderUseCase(executor, self._market, self._publisher)
        self._price_update_uc = HandlePriceUpdateUseCase(self._publisher)

        self.calculator = PositionCalculator(self.bot.config)
        self.current_state = BotState(self.bot.state)
        if self.bot.config.get("bot_type") == "straddle":
            # до двух открытых позиций (LONG и SHORT) — их ведёт StraddleRunner
            from app.services.straddle_runner import StraddleRunner
            self.straddle = StraddleRunner(self)
            await self.straddle.load()
            return

        result = await self.db.execute(
            select(Position).where(Position.bot_id == self.bot_id, Position.is_open == True)
        )
        self.position = result.scalar_one_or_none()
        await self._restore_state()

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

    @_in_session
    async def manual_entry(self, account_balance: float = None) -> Dict:
        if self.straddle:
            return await self.straddle.launch()
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

    @_in_session
    async def set_limit_entry(self, limit_price: float) -> Dict:
        if self.straddle:
            return {"success": False, "error": "Straddle запускается только вручную"}
        if self.current_state != BotState.IDLE:
            return {"success": False, "error": "Bot not in IDLE state"}
        try:
            self.bot.limit_entry_price = limit_price
            self.bot.state = BotState.WAITING
            await self.db.commit()
            await self.db.refresh(self.bot)
            self.current_state = BotState.WAITING

            from app.services.websocket import price_stream_manager
            await price_stream_manager.register_strategy(self.bot_id)

            logger.info(
                f"[WAITING] bot={self.bot_id} {self.bot.symbol} {self.bot.side} "
                f"— waiting for price {limit_price}"
            )
            return {"success": True, "limit_price": limit_price}
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error in set_limit_entry: {e}")
            return {"success": False, "error": str(e)}

    @_in_session
    async def arm_signal_entry(self) -> Dict:
        if self.straddle:
            return {"success": False, "error": "Straddle запускается только вручную"}
        if self.current_state != BotState.IDLE:
            return {"success": False, "error": "Bot not in IDLE state"}
        if not self.bot.config.get("entry_signal"):
            return {"success": False, "error": "Bot has no entry_signal in config"}
        try:
            self.bot.state = BotState.SIGNAL
            await self.db.commit()
            await self.db.refresh(self.bot)
            self.current_state = BotState.SIGNAL
            logger.info(f"[SIGNAL_WAIT] bot={self.bot_id} {self.bot.symbol} {self.bot.side} — waiting for entry signal")
            return {"success": True}
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error in arm_signal_entry: {e}")
            return {"success": False, "error": str(e)}

    async def signal_entry(self) -> Dict:
        """Вход по сработавшему сигналу — вызывается SignalEntryScheduler."""
        if self.current_state != BotState.SIGNAL:
            return {"success": False, "error": "Bot not in SIGNAL state"}
        self.current_state = BotState.IDLE  # manual_entry принимает только IDLE
        result = await self.manual_entry()
        if not result["success"]:
            self.current_state = BotState.SIGNAL
        return result

    @_in_session
    async def cancel_limit_entry(self) -> Dict:
        """Отменяет ожидание входа — и лимитного (WAITING), и по сигналу (SIGNAL)."""
        if self.current_state not in (BotState.WAITING, BotState.SIGNAL):
            return {"success": False, "error": "Bot not in WAITING or SIGNAL state"}
        try:
            was_waiting = self.current_state == BotState.WAITING
            self.bot.limit_entry_price = None
            self.bot.state = BotState.IDLE
            await self.db.commit()
            await self.db.refresh(self.bot)
            self.current_state = BotState.IDLE

            if was_waiting:
                from app.services.websocket import price_stream_manager
                price_stream_manager.unregister_strategy(self.bot_id)

            logger.info(f"[CANCEL_ENTRY] bot={self.bot_id} pending entry cancelled")
            return {"success": True}
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error in cancel_limit_entry: {e}")
            return {"success": False, "error": str(e)}

    @_in_session
    async def _execute_entry(self):
        if self._is_entering:
            return
        self._is_entering = True
        try:
            result = await self._open_uc.execute(self.bot, self.calculator, self.db)
            if result["success"]:
                self.position = result.pop("position")
                self.bot.limit_entry_price = None
                self.bot.state = BotState.PYRAMIDING
                await self.db.commit()
                self.current_state = BotState.PYRAMIDING
                logger.info(
                    f"[LIMIT_ENTRY] bot={self.bot_id} {self.bot.symbol} "
                    f"triggered @ {self.position.average_price}"
                )
            else:
                logger.error(f"[LIMIT_ENTRY] failed: {result.get('error')}")
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error in _execute_entry: {e}")
        finally:
            self._is_entering = False

    async def on_price_update(self, current_price: float):
        if self.straddle:
            async with self.session():
                await self.straddle.on_price(current_price)
            return

        # Handle WAITING state — check if limit price is hit
        if self.current_state == BotState.WAITING:
            limit_price = self.bot.limit_entry_price
            if limit_price:
                triggered = (
                    (self.bot.side == "LONG" and current_price <= limit_price) or
                    (self.bot.side == "SHORT" and current_price >= limit_price)
                )
                if triggered:
                    await self._execute_entry()
            return

        if self.current_state != BotState.PYRAMIDING:
            return
        if not self.position or not self.position.is_open:
            return
        if not self.position.is_bot_managed:
            # User took manual control of this position — bot stops touching it
            # entirely (no SL checks, no pyramiding, no trailing SL/PnL updates).
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
                    self.bot.side, self.calculator.orders, current_price,
                    trailing_enabled=self.position.trailing_enabled,
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

            # 2. Check TP hit — ловим по цене сами, одинаково для любой биржи:
            # даже если биржевой тейк уже закрыл позицию, у нас сделка тоже закроется
            if self.calculator.is_take_profit_hit(self.bot.side, current_price):
                logger.info(
                    f"[TP_HIT] bot={self.bot_id} symbol={self.bot.symbol} current={current_price} "
                    f"tp={self.calculator.take_profit_price(self.bot.side)}"
                )
                await self._close_position(current_price, "TP_HIT")
                return

            # 3. Check add-order trigger: добор пирамидинга или страховочный DCA
            if self.calculator.is_dca():
                add_order = self.calculator.should_add_dca_order(self.bot.side, current_price)
            else:
                add_order = self.calculator.should_add_order(self.bot.side, current_price, last_order_price)
            if add_order:
                if self._is_adding_order:
                    return
                logger.info(
                    f"[AVG TRIGGER] bot={self.bot_id} current={current_price} "
                    f"last_order={last_order_price} orders={orders_count}"
                )
                await self._add_pyramiding_order(current_price)
                return

            # 4. Позиция могла закрыться на бирже без нас (руками, ликвидация)
            if await self._reconcile_with_exchange(current_price):
                return

            # 5. Update trailing SL + PnL
            await self._price_update_uc.execute(self.bot, self.position, self.calculator, current_price)

        except Exception as e:
            logger.error(f"[ERROR] on_price_update bot={self.bot_id}: {e}", exc_info=True)

    async def _reconcile_with_exchange(self, current_price: float) -> bool:
        """Раз в RECONCILE_INTERVAL_SEC сверяет позицию с биржей. Если на бирже
        её уже нет — закрывает сделку у себя. True, если позиция закрыта."""
        now = time.time()
        if now - self._last_reconcile < RECONCILE_INTERVAL_SEC or not self._executor:
            return False
        self._last_reconcile = now
        try:
            size = await self._executor.get_open_position_size(self.bot.symbol, self.bot.side)
        except Exception as e:
            logger.warning(f"[RECONCILE] bot={self.bot_id} failed: {e}")
            return False
        if size is None or size > 0:
            return False
        logger.warning(
            f"[EXCHANGE_CLOSED] bot={self.bot_id} {self.bot.symbol} {self.bot.side} — "
            f"no position on exchange, closing locally @ {current_price}"
        )
        await self._close_position(current_price, "EXCHANGE_CLOSED", send_to_exchange=False)
        return True

    @_in_session
    async def _add_pyramiding_order(self, current_price: float):
        self._is_adding_order = True
        try:
            result = await self._add_order_uc.execute(
                self.bot, self.position, self.calculator, current_price, self.db
            )
            if not result["success"]:
                logger.error(f"Pyramiding order failed: {result.get('error')}")
            # Только что докупили — биржа может ещё не отдавать обновлённую позицию
            self._last_reconcile = time.time()
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error adding pyramiding order: {e}")
        finally:
            self._is_adding_order = False

    @_in_session
    async def _close_position(self, exit_price: float, exit_reason: str, send_to_exchange: bool = True):
        self._is_closing = True
        try:
            await self._close_uc.execute(
                self.bot, self.position, self.calculator, exit_price, exit_reason, self.db,
                send_to_exchange=send_to_exchange,
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

    @_in_session
    async def manual_close(self) -> Dict:
        if self.straddle:
            return await self.straddle.manual_close()
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
