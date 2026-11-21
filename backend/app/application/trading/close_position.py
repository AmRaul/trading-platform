from typing import Dict
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.ports.exchange_executor import ExchangeExecutor
from app.ports.event_publisher import EventPublisher
from app.domain.trading.position_calculator import PositionCalculator
from app.models import Bot, Position, Trade
from app.core.redis import delete_position_state
from app.services import exchange_issues
import logging

logger = logging.getLogger(__name__)


class ClosePositionUseCase:
    def __init__(self, executor: ExchangeExecutor, publisher: EventPublisher):
        self.executor = executor
        self.publisher = publisher

    async def execute(
        self,
        bot: Bot,
        position: Position,
        calculator: PositionCalculator,
        exit_price: float,
        exit_reason: str,
        db: AsyncSession,
        send_to_exchange: bool = True,
    ) -> Dict:
        """send_to_exchange=False — позиция уже закрыта на бирже (сверка),
        фиксируем сделку только у себя."""
        logger.info(
            f"[CLOSE] bot={bot.id} symbol={bot.symbol} side={bot.side} "
            f"reason={exit_reason} exit={exit_price} avg={position.average_price} "
            f"size={position.total_size:.2f} sl={position.current_sl}"
        )

        if send_to_exchange:
            # quantity=None — закрыть всю позицию: total_size у нас в USDT, а Bybit
            # ждёт количество в монетах (без него сам берёт размер позиции с биржи)
            close_result = await self.executor.close_position(
                symbol=bot.symbol,
                side=bot.side,
                quantity=None,
            )
            if not close_result or not close_result.get("success"):
                error = (close_result or {}).get("error") or "биржа не подтвердила закрытие"
                if getattr(self.executor, "can_verify", True):
                    # Исполнитель видит биржу и говорит, что позиция открыта: закрыть её
                    # только у себя — значит бросить живую позицию без стопа. Не закрываем,
                    # движок повторит закрытие (см. StrategyEngine._close_position).
                    logger.error(f"[CLOSE FAILED] bot={bot.id}: {error} — позиция остаётся под управлением")
                    exchange_issues.report(bot.id, "close", f"не закрылась на бирже ({exit_reason}): {error}")
                    return {"success": False, "error": error}
                # Cryptorg без ключа Bybit: проверить биржу нечем — как раньше закрываем у себя
                logger.error(f"[CLOSE UNVERIFIED] bot={bot.id}: {error} — closing locally anyway")
                exchange_issues.report(bot.id, "close_unverified", (
                    f"webhook закрытия ({exit_reason}) вернул ошибку: {error}. Сделка закрыта только у нас — "
                    f"проверь позицию в Cryptorg руками (ключ Bybit для сверки не задан)"), ttl_sec=6 * 3600)
            exchange_issues.clear(bot.id, "close")

        pnl = calculator.calculate_unrealized_pnl(
            bot.side, position.average_price, exit_price, position.total_size
        )
        pnl_percent = calculator.calculate_pnl_percent(bot.side, position.average_price, exit_price)

        # Исполнитель со ставкой комиссии (paper) — PnL сделки сразу за вычетом
        # комиссий: вход и доборы на total_size, выход — на тот же объём по цене выхода
        fees = None
        fee_rate = getattr(self.executor, "fee_rate", None)
        if isinstance(fee_rate, (int, float)) and fee_rate > 0:
            fees = fee_rate * position.total_size * (1 + exit_price / position.average_price)
            pnl -= fees

        first_order = calculator.orders[0]
        trade = Trade(
            bot_id=bot.id,
            position_id=position.id,
            symbol=bot.symbol,
            side=bot.side,
            entry_price=first_order.price,
            average_price=position.average_price,
            total_size=position.total_size,
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl=pnl,
            pnl_percent=pnl_percent,
            fees=fees,
            total_orders=position.order_count,
            opened_at=position.opened_at,
        )
        db.add(trade)

        position.is_open = False
        position.closed_at = datetime.utcnow()
        position.realized_pnl = pnl

        # Цикл с входом по сигналу — не переоткрываемся сразу, а снова ждём сигнал
        signal_cycle = bot.config.get("cycle", False) and bot.config.get("entry_signal")
        bot.state = "SIGNAL" if signal_cycle else "IDLE"
        bot.total_pnl += pnl
        bot.stopped_at = datetime.utcnow()

        await db.commit()
        await delete_position_state(str(bot.id))

        total_orders = position.order_count
        avg_price = position.average_price

        calculator.reset()

        logger.info(f"Position closed: {exit_reason}, PnL: {pnl:.2f} ({pnl_percent:.2f}%)")

        # Auto-cycle: reopen position immediately after close if enabled
        if bot.config.get("cycle", False) and not signal_cycle:
            import asyncio
            from app.services.websocket import price_stream_manager
            async def _reopen():
                try:
                    await price_stream_manager.register_strategy(bot.id)
                    engine = price_stream_manager.strategy_engines.get(bot.id)
                    if engine:
                        result = await engine.manual_entry()
                        if result.get("success"):
                            logger.info(f"[CYCLE] bot={bot.id} reopened after {exit_reason}")
                        else:
                            logger.warning(f"[CYCLE] bot={bot.id} reopen failed: {result.get('error')}")
                except Exception as e:
                    logger.error(f"[CYCLE] bot={bot.id} reopen error: {e}")
            asyncio.create_task(_reopen())

        await self.publisher.publish("position_closed", {
            "bot_id": bot.id,
            "symbol": bot.symbol,
            "side": bot.side,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "pnl": pnl,
            "pnl_percent": pnl_percent,
            "fees": fees,
            "total_orders": total_orders,
            "entry_price": first_order.price,
            "average_price": avg_price,
        })

        return {"success": True, "pnl": pnl, "pnl_percent": pnl_percent}
