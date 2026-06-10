from typing import Optional, List, Tuple
from app.domain.trading.entities import OrderInfo
import logging

logger = logging.getLogger(__name__)


class PositionCalculator:
    """Pure position math — no DB, no exchange dependencies."""

    def __init__(self, config: dict):
        self.config = config
        self.orders: List[OrderInfo] = []

    def calculate_average_price(self, orders: List[OrderInfo]) -> float:
        if not orders:
            return 0.0
        total_value = sum(o.price * o.size for o in orders)
        total_size = sum(o.size for o in orders)
        return total_value / total_size if total_size else 0.0

    def calculate_next_order_size(self) -> float:
        if not self.orders:
            return self.config["entry_size_usdt"]
        bot_type = self.config.get("bot_type", "pyramiding")
        if bot_type == "dca":
            multiplier = self.config.get("dca_multiplier", 1.0)
            return self.orders[-1].size * multiplier
        return self.orders[-1].size * self.config["pyramiding_multiplier"]

    def should_add_dca_order(self, side: str, current_price: float) -> bool:
        if not self.orders:
            return False
        if len(self.orders) >= self.config["order_count"]:
            return False

        step = self.config["step_percent"] / 100
        buffer = self.config.get("order_trigger_buffer_pct", 0.05) / 100
        effective_step = step - buffer

        avg_price = self.calculate_average_price(self.orders)

        if side == "LONG":
            return (avg_price - current_price) / avg_price >= effective_step
        else:
            return (current_price - avg_price) / avg_price >= effective_step

    def calculate_stop_loss(
        self,
        side: str,
        orders: List[OrderInfo],
        current_price: float,
    ) -> Tuple[float, str]:
        if not orders:
            return 0.0, "none"

        sl_initial = self.config.get("sl_initial")
        if sl_initial is None:
            return 0.0, "disabled"

        order_count = len(orders)

        if order_count == 1:
            sl_pct = sl_initial / 100
            first = orders[0]
            if side == "LONG":
                return first.price * (1 - sl_pct), "initial"
            else:
                return first.price * (1 + sl_pct), "initial"

        avg_price = self.calculate_average_price(orders)

        if order_count == 2 and self.config.get("sl_breakeven_on_order2", True):
            dynamic_sl = avg_price
        elif order_count == 2:
            sl_pct = sl_initial / 100
            first = orders[0]
            if side == "LONG":
                return first.price * (1 - sl_pct), "initial"
            else:
                return first.price * (1 + sl_pct), "initial"
        else:
            offset = self.config.get("sl_after_order3", self.config.get("sl_dynamic_offset", 2.0)) / 100
            if side == "LONG":
                dynamic_sl = avg_price * (1 - offset)
            else:
                dynamic_sl = avg_price * (1 + offset)

        if self.config.get("use_trailing", False):
            trailing_pct = self.config["trailing_percent"] / 100
            if side == "LONG":
                trailing_sl = current_price * (1 - trailing_pct)
                final_sl = max(dynamic_sl, trailing_sl)
            else:
                trailing_sl = current_price * (1 + trailing_pct)
                if trailing_sl <= current_price:
                    return dynamic_sl, "dynamic"
                final_sl = min(dynamic_sl, trailing_sl)

            sl_type = "trailing" if final_sl == trailing_sl else "dynamic"
            return final_sl, sl_type

        return dynamic_sl, "dynamic"

    def should_add_order(self, side: str, current_price: float, last_order_price: float) -> bool:
        if not self.orders:
            return False
        if len(self.orders) >= self.config["order_count"]:
            return False

        step = self.config["step_percent"] / 100
        buffer = self.config.get("order_trigger_buffer_pct", 0.05) / 100
        effective_step = step - buffer

        if side == "LONG":
            return current_price >= last_order_price * (1 + effective_step)
        else:
            return current_price <= last_order_price * (1 - effective_step)

    def is_stop_loss_hit(
        self,
        side: str,
        current_price: float,
        stop_loss: float,
        slippage_pct: float = 0.05,
    ) -> bool:
        if stop_loss == 0:
            return False
        buffer = stop_loss * (slippage_pct / 100)
        if side == "LONG":
            return current_price <= (stop_loss - buffer)
        else:
            return current_price >= (stop_loss + buffer)

    def calculate_unrealized_pnl(
        self,
        side: str,
        average_price: float,
        current_price: float,
        total_size: float,
    ) -> float:
        if average_price == 0 or total_size == 0:
            return 0.0
        if side == "LONG":
            return (current_price - average_price) * total_size
        else:
            return (average_price - current_price) * total_size

    def calculate_pnl_percent(self, side: str, average_price: float, current_price: float) -> float:
        if average_price == 0:
            return 0.0
        if side == "LONG":
            return ((current_price - average_price) / average_price) * 100
        else:
            return ((average_price - current_price) / average_price) * 100

    def calculate_sl_percent(self, order_count: int) -> float:
        sl_initial = self.config.get("sl_initial")
        if sl_initial is None:
            return 0.0
        if order_count <= 1:
            return float(sl_initial)
        if order_count == 2:
            return 0.0 if self.config.get("sl_breakeven_on_order2", True) else float(sl_initial)
        return -float(self.config.get("sl_after_order3", self.config.get("sl_breakeven_plus", 0.5)))

    def add_order(self, order: OrderInfo):
        self.orders.append(order)

    def get_last_order_price(self) -> Optional[float]:
        return self.orders[-1].price if self.orders else None

    def get_total_size(self) -> float:
        return sum(o.size for o in self.orders)

    def reset(self):
        self.orders = []
