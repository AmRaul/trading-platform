from typing import Optional, List, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class OrderInfo:
    """Single order information"""
    order_number: int
    price: float
    size: float


class PositionManager:
    """Manages position calculations (avg price, SL, pyramiding)"""

    def __init__(self, config: dict):
        self.config = config
        self.orders: List[OrderInfo] = []

    def calculate_average_price(self, orders: List[OrderInfo]) -> float:
        """Calculate average entry price across all orders"""
        if not orders:
            return 0.0

        total_value = sum(order.price * order.size for order in orders)
        total_size = sum(order.size for order in orders)

        if total_size == 0:
            return 0.0

        return total_value / total_size

    def calculate_next_order_size(self, account_balance: float = None) -> float:
        """
        Calculate size for next order based on pyramiding multiplier

        Args:
            account_balance: Not used anymore, kept for compatibility

        Returns:
            Order size in USDT
        """
        order_count = len(self.orders)

        if order_count == 0:
            # First order: use fixed USDT size from config
            return self.config["entry_size_usdt"]

        # Subsequent orders: previous_size * pyramiding_multiplier
        last_order = self.orders[-1]
        next_size = last_order.size * self.config["pyramiding_multiplier"]

        return next_size

    def calculate_stop_loss(
        self,
        side: str,
        orders: List[OrderInfo],
        current_price: float
    ) -> Tuple[float, str]:
        """
        Calculate stop loss based on order count and position

        Strategy:
        - Order 1: Initial SL from first order price ± sl_initial%
        - Order 2+: Dynamic SL from average price ± sl_dynamic_offset%
        - If use_trailing=True: Compare dynamic vs trailing, use better one

        Trailing Stop Logic (Order 2+):
        - Dynamic SL: avg_price ± sl_dynamic_offset% (fixed)
        - Trailing SL: current_price ± trailing_percent% (moves with price)
        - LONG: Use max(dynamic_sl, trailing_sl) → higher is better protection
        - SHORT: Use min(dynamic_sl, trailing_sl) → lower is better protection

        Returns: (stop_loss_price, sl_type)
        sl_type: 'initial', 'dynamic', 'trailing'
        """
        if not orders:
            return 0.0, "none"

        order_count = len(orders)

        # First order: use initial SL
        if order_count == 1:
            first_order = orders[0]
            sl_percent = self.config["sl_initial"] / 100

            if side == "LONG":
                sl_price = first_order.price * (1 - sl_percent)
            else:  # SHORT
                sl_price = first_order.price * (1 + sl_percent)

            return sl_price, "initial"

        # Order 2+: use dynamic SL from average price
        avg_price = self.calculate_average_price(orders)
        sl_offset = self.config["sl_dynamic_offset"] / 100

        if side == "LONG":
            dynamic_sl = avg_price * (1 + sl_offset)
        else:  # SHORT
            dynamic_sl = avg_price * (1 - sl_offset)

        # Check if trailing stop is enabled
        if self.config.get("use_trailing", False):
            trailing_percent = self.config["trailing_percent"] / 100

            if side == "LONG":
                trailing_sl = current_price * (1 - trailing_percent)
                # Use the higher SL (better protection)
                final_sl = max(dynamic_sl, trailing_sl)
            else:  # SHORT
                trailing_sl = current_price * (1 + trailing_percent)
                # Use the lower SL (better protection)
                final_sl = min(dynamic_sl, trailing_sl)

            sl_type = "trailing" if final_sl == trailing_sl else "dynamic"
            return final_sl, sl_type

        return dynamic_sl, "dynamic"

    def should_add_order(
        self,
        side: str,
        current_price: float,
        last_order_price: float
    ) -> bool:
        """Check if we should add a new pyramiding order"""
        if not self.orders:
            return False

        # Check if max orders reached
        if len(self.orders) >= self.config["order_count"]:
            return False

        step_percent = self.config["step_percent"] / 100

        if side == "LONG":
            # Price should be higher than last order by step_percent
            target_price = last_order_price * (1 + step_percent)
            return current_price >= target_price
        else:  # SHORT
            # Price should be lower than last order by step_percent
            target_price = last_order_price * (1 - step_percent)
            return current_price <= target_price

    def is_stop_loss_hit(
        self,
        side: str,
        current_price: float,
        stop_loss: float
    ) -> bool:
        """Check if stop loss has been hit"""
        if stop_loss == 0:
            return False

        if side == "LONG":
            return current_price <= stop_loss
        else:  # SHORT
            return current_price >= stop_loss

    def calculate_unrealized_pnl(
        self,
        side: str,
        average_price: float,
        current_price: float,
        total_size: float,
        leverage: int = 1
    ) -> float:
        """Calculate unrealized PnL"""
        if average_price == 0 or total_size == 0:
            return 0.0

        if side == "LONG":
            pnl = (current_price - average_price) * total_size
        else:  # SHORT
            pnl = (average_price - current_price) * total_size

        return pnl

    def calculate_pnl_percent(
        self,
        side: str,
        average_price: float,
        current_price: float
    ) -> float:
        """Calculate PnL percentage"""
        if average_price == 0:
            return 0.0

        if side == "LONG":
            pnl_percent = ((current_price - average_price) / average_price) * 100
        else:  # SHORT
            pnl_percent = ((average_price - current_price) / average_price) * 100

        return pnl_percent

    def add_order(self, order: OrderInfo):
        """Add order to tracking"""
        self.orders.append(order)

    def get_last_order_price(self) -> Optional[float]:
        """Get price of last order"""
        if not self.orders:
            return None
        return self.orders[-1].price

    def get_total_size(self) -> float:
        """Get total position size"""
        return sum(order.size for order in self.orders)

    def reset(self):
        """Reset position manager"""
        self.orders = []
