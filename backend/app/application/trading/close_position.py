from typing import Dict
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.ports.exchange_executor import ExchangeExecutor
from app.ports.event_publisher import EventPublisher
from app.domain.trading.position_calculator import PositionCalculator
from app.models import Bot, Position, Trade
from app.core.redis import delete_position_state
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
    ) -> Dict:
        logger.info(
            f"[CLOSE] bot={bot.id} symbol={bot.symbol} side={bot.side} "
            f"reason={exit_reason} exit={exit_price} avg={position.average_price} "
            f"size={position.total_size:.2f} sl={position.current_sl}"
        )

        close_result = await self.executor.close_position(
            symbol=bot.symbol,
            side=bot.side,
            quantity=position.total_size,
        )
        if not close_result or not close_result.get("success"):
            logger.error("Failed to close position on exchange — closing locally anyway")

        pnl = calculator.calculate_unrealized_pnl(
            bot.side, position.average_price, exit_price, position.total_size
        )
        pnl_percent = calculator.calculate_pnl_percent(bot.side, position.average_price, exit_price)

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
            total_orders=position.order_count,
            opened_at=position.opened_at,
        )
        db.add(trade)

        position.is_open = False
        position.closed_at = datetime.utcnow()
        position.realized_pnl = pnl

        bot.state = "IDLE"
        bot.total_pnl += pnl
        bot.stopped_at = datetime.utcnow()

        await db.commit()
        await delete_position_state(str(bot.id))

        total_orders = position.order_count
        avg_price = position.average_price

        calculator.reset()

        logger.info(f"Position closed: {exit_reason}, PnL: {pnl:.2f} ({pnl_percent:.2f}%)")

        # Auto-cycle: reopen position immediately after close if enabled
        if bot.config.get("cycle", False):
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
            "total_orders": total_orders,
            "entry_price": first_order.price,
            "average_price": avg_price,
        })

        return {"success": True, "pnl": pnl, "pnl_percent": pnl_percent}
