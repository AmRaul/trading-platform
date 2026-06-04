from app.ports.event_publisher import EventPublisher
from app.domain.trading.position_calculator import PositionCalculator
from app.models import Bot, Position
from app.core.redis import set_position_state
import logging

logger = logging.getLogger(__name__)


class HandlePriceUpdateUseCase:
    """Updates trailing SL and unrealized PnL on each price tick."""

    def __init__(self, publisher: EventPublisher):
        self.publisher = publisher

    async def execute(
        self,
        bot: Bot,
        position: Position,
        calculator: PositionCalculator,
        current_price: float,
    ) -> None:
        pnl = calculator.calculate_unrealized_pnl(
            bot.side, position.average_price, current_price, position.total_size
        )

        sl_price, sl_type = calculator.calculate_stop_loss(
            bot.side, calculator.orders, current_price
        )

        old_sl = position.current_sl
        sl_moved = False
        min_move = old_sl * 0.0001

        if bot.side == "LONG":
            if sl_price > position.current_sl + min_move:
                position.current_sl = sl_price
                sl_moved = True
        else:
            if sl_price < position.current_sl - min_move:
                position.current_sl = sl_price
                sl_moved = True

        if sl_moved:
            logger.info(f"Trailing SL moved: {old_sl:.5f} → {sl_price:.5f} (type: {sl_type})")
            await self.publisher.publish("trailing_stop_moved", {
                "bot_id": bot.id,
                "symbol": bot.symbol,
                "side": bot.side,
                "old_sl": old_sl,
                "new_sl": sl_price,
                "sl_type": sl_type,
                "current_price": current_price,
                "unrealized_pnl": pnl,
            })

        position.unrealized_pnl = pnl

        state = {
            "bot_id": bot.id,
            "position_id": position.id,
            "symbol": bot.symbol,
            "side": bot.side,
            "average_price": position.average_price,
            "total_size": position.total_size,
            "current_sl": position.current_sl,
            "unrealized_pnl": pnl,
            "order_count": position.order_count,
            "last_order_price": calculator.get_last_order_price(),
            "state": "PYRAMIDING",
        }
        await set_position_state(str(bot.id), state)
