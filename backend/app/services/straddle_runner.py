"""
Исполнение straddle-бота (TODO/6): StraddleCalculator решает, раннер исполняет
на бирже и пишет в БД. Используется StrategyEngine для bot_type=straddle.

На бирже две реальные позиции по монете — LONG и SHORT (Bybit — в режиме хеджа).
Каждая — обычная Position/Order/Trade, состояние конструкции (точка запуска,
фаза, стоп, пилы) — Bot.runtime_state: переживает рестарт бэкенда.
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Optional

from sqlalchemy import select

from app.core.redis import delete_position_state, set_position_state
from app.domain.trading.straddle import (
    ADD, CLOSE, FINISH, LONG, OPEN, SHORT, SIDES, StraddleAction, StraddleCalculator, StraddleState, avg_price,
)
from app.models import Order, Position, Trade

logger = logging.getLogger(__name__)

PERSIST_INTERVAL_SEC = 15      # сдвиги стопа без сделок пишем в БД не чаще
RECONCILE_INTERVAL_SEC = 60
MAX_ACTIONS_PER_TICK = 8
NO_CYCLE_REASONS = ("MANUAL_CLOSE", "EXCHANGE_CLOSED")


class StraddleRunner:
    def __init__(self, engine):
        self.engine = engine
        self.calc = StraddleCalculator(engine.bot.config)
        rs = engine.bot.runtime_state
        self.state: Optional[StraddleState] = StraddleState.from_dict(rs) if rs else None
        self.positions: Dict[str, Position] = {}
        self._busy = False
        self._last_persist = 0.0
        self._last_reconcile = time.time()

    @property
    def bot(self):
        return self.engine.bot

    @property
    def db(self):
        return self.engine.db

    async def load(self):
        """Открытые позиции конструкции (до двух — LONG и SHORT)."""
        result = await self.db.execute(
            select(Position).where(Position.bot_id == self.bot.id, Position.is_open == True)  # noqa: E712
        )
        self.positions = {p.side: p for p in result.scalars().all()}

    def snapshot(self, price: float) -> dict:
        st = self.state
        u = st.unrealized(price)
        return {**st.to_dict(), "price": price, "pnl": {LONG: u[LONG], SHORT: u[SHORT], "total": st.total(price)},
                "levels": {LONG: self.calc.level(st.anchor, LONG, 1), SHORT: self.calc.level(st.anchor, SHORT, 1)}}

    # --- запуск / ручное закрытие ---

    async def launch(self) -> Dict:
        if self.bot.state != "IDLE":
            return {"success": False, "error": "Bot not in IDLE state"}
        ensure = getattr(self.engine._executor, "ensure_hedge_mode", None)
        if ensure:
            res = await ensure(self.bot.symbol)
            if not res.get("success"):
                return {"success": False, "error": f"Bybit: не удалось включить режим хеджа — {res.get('error')}"}
        price = await self._ticker_price()
        if price is None:
            return {"success": False, "error": "Failed to get ticker price"}

        self.state = self.calc.start(price, time.time())
        self.positions = {}
        await self._run_actions(price)
        if not any(self.state.legs.values()):
            self.state = None
            await self.db.rollback()
            return {"success": False, "error": "Биржа не открыла ни одну сторону"}

        self.bot.state = "STRADDLE"
        self.bot.started_at = datetime.utcnow()
        await self._persist()
        logger.info(f"[STRADDLE] bot={self.bot.id} {self.bot.symbol} launched @ {price}")

        from app.services.websocket import price_stream_manager
        await price_stream_manager.register_strategy(self.bot.id)
        opened = [s for s in SIDES if self.state.legs[s]]
        return {"success": True, "anchor": price, "opened": opened}

    async def manual_close(self) -> Dict:
        if self.bot.state != "STRADDLE" or not self.state:
            return {"success": False, "error": "Straddle is not running"}
        price = await self._ticker_price()
        if price is None:
            return {"success": False, "error": "Failed to get ticker price"}
        self.state.done, self.state.exit_reason = True, "MANUAL_CLOSE"
        await self._close_rest(price)
        await self._finish()
        return {"success": True, "exit_price": price, "pnl": self.state.realized}

    # --- тики ---

    async def on_price(self, price: float):
        st = self.state
        if self._busy or not st or st.done or self.bot.state != "STRADDLE":
            return
        if any(p.is_bot_managed is False for p in self.positions.values()):
            return  # пользователь взял позиции на себя
        self._busy = True
        try:
            changed = self.calc.update_marks(st, price)
            acted = await self._run_actions(price)
            if st.done:
                await self._close_rest(price)
                await self._finish()
                return
            if not acted and await self._reconcile(price):
                return
            if acted or (changed and time.time() - self._last_persist >= PERSIST_INTERVAL_SEC):
                await self._persist()
            await set_position_state(str(self.bot.id), {
                "bot_id": self.bot.id, "symbol": self.bot.symbol, "state": "STRADDLE",
                "straddle": self.snapshot(price),
            })
        except Exception as e:
            await self.db.rollback()
            logger.error(f"[STRADDLE] bot={self.bot.id} tick error: {e}", exc_info=True)
        finally:
            self._busy = False

    async def _run_actions(self, price: float) -> bool:
        st, acted = self.state, False
        for _ in range(MAX_ACTIONS_PER_TICK):
            action = self.calc.decide(st, price, time.time())
            if action is None:
                break
            if action.kind == FINISH:
                self.calc.apply(st, action, price, time.time())
            elif not await self._execute(action, price):
                break  # биржа отказала — решение не применено, повторим на следующем тике
            acted = True
            if st.done:
                break
        return acted

    # --- исполнение ---

    async def _ticker_price(self) -> Optional[float]:
        ticker = await self.engine._market.get_ticker(self.bot.symbol)
        return float(ticker["lastPrice"]) if ticker and ticker.get("lastPrice") else None

    def _exchange_sl_percent(self, side: str) -> Optional[float]:
        """Страховочный стоп рабочей стороны для биржи, % от её средней (+ — в сторону убытка).
        Трейлинг и пилу бэкенд ведёт сам по тикам."""
        st = self.state
        if st.working != side or not st.stop:
            return None
        avg = avg_price(st.legs[side])
        return round((avg - st.stop) / avg * 100 if side == LONG else (st.stop - avg) / avg * 100, 4)

    async def _execute(self, action: StraddleAction, price: float) -> bool:
        ex, st, side, symbol = self.engine._executor, self.state, action.side, self.bot.symbol
        logger.info(f"[STRADDLE] bot={self.bot.id} {action.kind} {side} {action.usdt:.2f} USDT "
                    f"reason={action.reason} price={price} anchor={st.anchor} phase={st.phase}")

        if action.kind == OPEN:
            res = await ex.open_position(symbol=symbol, side=side.lower(), order_volume_usdt=action.usdt,
                                         leverage=self.bot.config.get("leverage", 10),
                                         sl_percent=None, tp_percent=None)
            if not res or not res.get("success"):
                logger.error(f"[STRADDLE] open {side} failed: {res and res.get('error')}")
                return False
            fill = await self._ticker_price() or price
            self.calc.apply(st, action, fill, time.time())
            pos = Position(bot_id=self.bot.id, symbol=symbol, side=side, total_size=action.usdt,
                           average_price=fill, order_count=1, current_sl=0.0, is_open=True,
                           is_bot_managed=True, trailing_enabled=True)
            self.db.add(pos)
            await self.db.flush()
            self.db.add(self._order(pos, action, fill, 1, res))
            self.positions[side] = pos
            return True

        pos = self.positions.get(side)
        if action.kind == ADD:
            res = await ex.add_to_position(symbol=symbol, side=side.lower(), amount_usdt=action.usdt)
            if not res or not res.get("success"):
                logger.error(f"[STRADDLE] add {side} failed: {res and res.get('error')}")
                return False
            fill = await self._ticker_price() or price
            self.calc.apply(st, action, fill, time.time())
            if pos:
                pos.order_count += 1
                pos.total_size = sum(u for _, u in st.legs[side])
                pos.average_price = avg_price(st.legs[side])
                pos.current_sl = st.stop
                self.db.add(self._order(pos, action, fill, pos.order_count, res))
            upd = await ex.update_stop_and_tp(symbol=symbol, side=side.lower(),
                                              sl_percent=self._exchange_sl_percent(side), tp_percent=None)
            if not (upd and upd.get("success")):
                logger.warning(f"[STRADDLE] failed to update exchange stop for {side}")
            return True

        if action.kind == CLOSE:
            if action.reason != "EXCHANGE_CLOSED":
                res = await ex.close_position(symbol=symbol, side=side, quantity=None)
                if not res or not res.get("success"):
                    logger.error(f"[STRADDLE] close {side} failed on exchange — closing locally anyway")
            fill = price if action.reason == "EXCHANGE_CLOSED" else (await self._ticker_price() or price)
            orders = st.legs[side]
            entry, avg, size = orders[0][0], avg_price(orders), sum(u for _, u in orders)
            pnl = self.calc.apply(st, action, fill, time.time())
            if pos:
                self.db.add(Trade(
                    bot_id=self.bot.id, position_id=pos.id, symbol=symbol, side=side,
                    entry_price=entry, average_price=avg, total_size=size, exit_price=fill,
                    exit_reason=f"STRADDLE_{action.reason}", pnl=pnl, pnl_percent=pnl / size * 100 if size else 0,
                    total_orders=len(orders), opened_at=pos.opened_at or datetime.utcnow(),
                    notes=f"anchor={st.anchor} rearms={st.rearms}",
                ))
                pos.is_open = False
                pos.closed_at = datetime.utcnow()
                pos.realized_pnl = pnl
            self.positions.pop(side, None)
            self.bot.total_pnl = (self.bot.total_pnl or 0.0) + pnl
            await self.engine._publisher.publish("position_closed", {
                "bot_id": self.bot.id, "symbol": symbol, "side": side, "exit_price": fill,
                "exit_reason": f"STRADDLE_{action.reason}", "pnl": pnl, "total_orders": len(orders),
                "entry_price": entry, "average_price": avg,
            })
            return True
        return False

    def _order(self, pos: Position, action: StraddleAction, fill: float, number: int, res: dict) -> Order:
        return Order(position_id=pos.id, bot_id=self.bot.id, exchange_order_id=res.get("orderId"),
                     symbol=self.bot.symbol, side=action.side.lower(), size=action.usdt, price=fill,
                     order_number=number, status="FILLED", filled_at=datetime.utcnow())

    async def _close_rest(self, price: float):
        """Конструкция завершена — закрыть оставшиеся стороны."""
        for side in SIDES:
            if self.state.legs[side]:
                await self._execute(StraddleAction(CLOSE, side, reason=self.state.exit_reason), price)

    async def _reconcile(self, price: float) -> bool:
        """Сторона могла закрыться на бирже без нас (руками, ликвидация) — тогда
        логика пары сломана: закрываем конструкцию целиком."""
        st, now = self.state, time.time()
        if now - self._last_reconcile < RECONCILE_INTERVAL_SEC:
            return False
        self._last_reconcile = now
        for side in SIDES:
            if not st.legs[side]:
                continue
            try:
                size = await self.engine._executor.get_open_position_size(self.bot.symbol, side)
            except Exception as e:
                logger.warning(f"[STRADDLE] reconcile failed: {e}")
                return False
            if size is not None and size <= 0:
                logger.warning(f"[STRADDLE] bot={self.bot.id} {side} closed on exchange — finishing construct")
                await self._execute(StraddleAction(CLOSE, side, reason="EXCHANGE_CLOSED"), price)
                st.done, st.exit_reason = True, "EXCHANGE_CLOSED"
                await self._close_rest(price)
                await self._finish()
                return True
        return False

    async def _persist(self):
        self.bot.runtime_state = self.state.to_dict()
        w = self.state.working
        if w and w in self.positions:
            self.positions[w].current_sl = self.state.stop
        await self.db.commit()
        self._last_persist = time.time()

    async def _finish(self):
        st = self.state
        logger.info(f"[STRADDLE] bot={self.bot.id} finished: {st.exit_reason} realized={st.realized:.4f}")
        self.bot.state = "IDLE"
        self.bot.stopped_at = datetime.utcnow()
        self.bot.runtime_state = st.to_dict()
        await self.db.commit()
        await delete_position_state(str(self.bot.id))
        await self.engine._publisher.publish("straddle_finished", {
            "bot_id": self.bot.id, "symbol": self.bot.symbol, "reason": st.exit_reason,
            "realized": st.realized, "rearms": st.rearms,
        })
        from app.services.websocket import price_stream_manager
        price_stream_manager.unregister_strategy(self.bot.id)

        if self.bot.config.get("cycle") and st.exit_reason not in NO_CYCLE_REASONS:
            bot_id = self.bot.id

            async def _relaunch():
                try:
                    await price_stream_manager.register_strategy(bot_id)
                    engine = price_stream_manager.strategy_engines.get(bot_id)
                    res = await engine.manual_entry() if engine else {"success": False}
                    logger.info(f"[STRADDLE] bot={bot_id} cycle relaunch: {res}")
                except Exception as e:
                    logger.error(f"[STRADDLE] bot={bot_id} cycle relaunch error: {e}")
            asyncio.create_task(_relaunch())
