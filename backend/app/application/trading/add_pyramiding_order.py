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


class AddPyramidingOrderUseCase:
    def __init__(self, executor: ExchangeExecutor, market_data: MarketData, publisher: EventPublisher):
        self.executor = executor
        self.market_data = market_data
        self.publisher = publisher

    async def execute(
        self,
        bot: Bot,
        position: Position,
        calculator: PositionCalculator,
        trigger_price: float,
        db: AsyncSession,
    ) -> Dict:
        order_size_usdt = calculator.calculate_next_order_size()
        order_number = len(calculator.orders) + 1

        logger.info(
            f"[AVG ORDER] bot={bot.id} symbol={bot.symbol} side={bot.side} "
            f"order=#{order_number} size={order_size_usdt:.2f} USDT price={trigger_price}"
        )

        order_result = await self.executor.add_to_position(
            symbol=bot.symbol,
            side=bot.side.lower(),
            amount_usdt=order_size_usdt,
        )
        if not order_result or not order_result.get("success"):
            logger.error("Failed to place pyramiding order")
            return {"success": False, "error": "Exchange rejected order"}

        ticker = await self.market_data.get_ticker(bot.symbol)
        fill_price = float(ticker["lastPrice"]) if ticker and ticker.get("lastPrice") else trigger_price
        logger.info(
            f"[AVG FILL] trigger={trigger_price} fill={fill_price} "
            f"slippage={fill_price - trigger_price:+.6f}"
        )

        order = Order(
            position_id=position.id,
            bot_id=bot.id,
            exchange_order_id=order_result.get("orderId"),
            symbol=bot.symbol,
            side=bot.side.lower(),
            size=order_size_usdt,
            price=fill_price,
            order_number=order_number,
            status="FILLED",
            filled_at=datetime.utcnow(),
        )
        db.add(order)

        calculator.add_order(OrderInfo(order_number, fill_price, order_size_usdt))

        avg_price = calculator.calculate_average_price(calculator.orders)
        total_size = calculator.get_total_size()
        sl_price, _ = calculator.calculate_stop_loss(bot.side, calculator.orders, fill_price)

        position.average_price = avg_price
        position.total_size = total_size
        position.current_sl = sl_price
        position.order_count = order_number

        sl_pct = calculator.calculate_sl_percent(order_number)
        max_orders = bot.config.get("order_count", 4)
        # Set TP only on the last pyramiding order — earlier orders only update SL
        tp_pct = bot.config.get("tp_percent", 3.0) if order_number >= max_orders else None

        logger.info(
            f"[SL/TP UPDATE] order={order_number}/{max_orders} sl={sl_pct}% "
            f"tp={'disabled' if tp_pct is None else f'{tp_pct}%'}"
        )

        update_result = await self.executor.update_stop_and_tp(
            symbol=bot.symbol,
            side=bot.side.lower(),
            sl_percent=sl_pct,
            tp_percent=tp_pct,
        )
        if not (update_result and update_result.get("success")):
            logger.warning("Failed to update SL/TP on exchange")

        await db.commit()

        state = {
            "bot_id": bot.id,
            "position_id": position.id,
            "symbol": bot.symbol,
            "side": bot.side,
            "average_price": avg_price,
            "total_size": total_size,
            "current_sl": sl_price,
            "unrealized_pnl": position.unrealized_pnl,
            "order_count": order_number,
            "last_order_price": calculator.get_last_order_price(),
            "state": "PYRAMIDING",
        }
        await set_position_state(str(bot.id), state)

        unrealized_pnl = calculator.calculate_unrealized_pnl(bot.side, avg_price, fill_price, total_size)

        logger.info(
            f"Pyramiding order added: #{order_number} @ {fill_price} "
            f"(trigger: {trigger_price}), avg: {avg_price}, SL: {sl_price}"
        )

        await self.publisher.publish("pyramiding_order_added", {
            "bot_id": bot.id,
            "symbol": bot.symbol,
            "side": bot.side,
            "order_number": order_number,
            "price": fill_price,
            "trigger_price": trigger_price,
            "size": order_size_usdt,
            "new_average_price": avg_price,
            "new_sl": sl_price,
            "total_size": total_size,
            "last_order_price": fill_price,
            "unrealized_pnl": unrealized_pnl,
        })

        return {"success": True, "order_number": order_number, "fill_price": fill_price}
