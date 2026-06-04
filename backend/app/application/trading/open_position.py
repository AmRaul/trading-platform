from typing import Dict
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.ports.exchange_executor import ExchangeExecutor
from app.ports.market_data import MarketData
from app.ports.event_publisher import EventPublisher
from app.domain.trading.entities import OrderInfo
from app.domain.trading.position_calculator import PositionCalculator
from app.models import Bot, Position, Order
from app.core.redis import set_position_state
import logging

logger = logging.getLogger(__name__)


class OpenPositionUseCase:
    def __init__(self, executor: ExchangeExecutor, market_data: MarketData, publisher: EventPublisher):
        self.executor = executor
        self.market_data = market_data
        self.publisher = publisher

    async def execute(self, bot: Bot, calculator: PositionCalculator, db: AsyncSession) -> Dict:
        order_size_usdt = calculator.calculate_next_order_size()

        ticker = await self.market_data.get_ticker(bot.symbol)
        if not ticker:
            return {"success": False, "error": "Failed to get ticker price"}

        current_price = float(ticker["lastPrice"])
        sl_percent = bot.config["sl_initial"]
        tp_percent = bot.config.get("tp_percent", 3.0)

        logger.info(
            f"[OPEN] bot={bot.id} symbol={bot.symbol} side={bot.side} "
            f"size={order_size_usdt:.2f} USDT price={current_price} SL={sl_percent}% TP={tp_percent}%"
        )

        order_result = await self.executor.open_position(
            symbol=bot.symbol,
            side=bot.side.lower(),
            order_volume_usdt=order_size_usdt,
            leverage=bot.config["leverage"],
            sl_percent=sl_percent,
            tp_percent=tp_percent,
        )

        if not order_result or not order_result.get("success"):
            return {"success": False, "error": order_result.get("error", "Failed to place order")}

        position = Position(
            bot_id=bot.id,
            symbol=bot.symbol,
            side=bot.side,
            total_size=order_size_usdt,
            average_price=current_price,
            order_count=1,
            is_open=True,
        )
        db.add(position)
        await db.flush()

        order = Order(
            position_id=position.id,
            bot_id=bot.id,
            exchange_order_id=order_result.get("orderId"),
            symbol=bot.symbol,
            side=bot.side.lower(),
            size=order_size_usdt,
            price=current_price,
            order_number=1,
            status="FILLED",
            filled_at=datetime.utcnow(),
        )
        db.add(order)

        calculator.add_order(OrderInfo(1, current_price, order_size_usdt))

        sl_price, _ = calculator.calculate_stop_loss(bot.side, calculator.orders, current_price)
        position.current_sl = sl_price

        bot.state = "PYRAMIDING"
        bot.started_at = datetime.utcnow()

        await db.commit()

        state = {
            "bot_id": bot.id,
            "position_id": position.id,
            "symbol": bot.symbol,
            "side": bot.side,
            "average_price": position.average_price,
            "total_size": position.total_size,
            "current_sl": position.current_sl,
            "unrealized_pnl": 0.0,
            "order_count": position.order_count,
            "last_order_price": calculator.get_last_order_price(),
            "state": "PYRAMIDING",
        }
        await set_position_state(str(bot.id), state)

        logger.info(f"Position opened: bot={bot.id} {order_size_usdt} USDT @ {current_price}")

        return {
            "success": True,
            "order_id": order.id,
            "price": current_price,
            "size": order_size_usdt,
            "sl": sl_price,
            "position": position,
        }
