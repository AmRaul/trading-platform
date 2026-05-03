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
        - Order 2: Breakeven SL (avg price)
        - If use_trailing=True: Compare dynamic vs trailing, use better one

        Trailing Stop Logic (Order 2+):
        - Dynamic SL: avg_price ± sl_after_order3% (fixed, order 3+)
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

        # Order 2+: SL based on order count
        avg_price = self.calculate_average_price(orders)

        if order_count == 2 and self.config.get("sl_breakeven_on_order2", True):
            dynamic_sl = avg_price
        elif order_count == 2:
            # Keep initial SL (from first order price)
            first_order = orders[0]
            sl_percent = self.config["sl_initial"] / 100
            if side == "LONG":
                return first_order.price * (1 - sl_percent), "initial"
            else:
                return first_order.price * (1 + sl_percent), "initial"
        else:
            sl_offset = self.config.get("sl_after_order3", self.config.get("sl_dynamic_offset", 2.0)) / 100
            if side == "LONG":
                # SL below avg: protect profit from a drop
                dynamic_sl = avg_price * (1 - sl_offset)
            else:  # SHORT
                # SL above avg: protect profit from a rise
                dynamic_sl = avg_price * (1 + sl_offset)

        # Check if trailing stop is enabled
        if self.config.get("use_trailing", False):
            trailing_percent = self.config["trailing_percent"] / 100

            if side == "LONG":
                # Trailing SL follows price up: price - trailing%
                trailing_sl = current_price * (1 - trailing_percent)
                # Use whichever SL is higher (better protection)
                final_sl = max(dynamic_sl, trailing_sl)
            else:  # SHORT
                # Trailing SL follows price down: price + trailing%
                trailing_sl = current_price * (1 + trailing_percent)
                # Trailing SL must be ABOVE current price
                if trailing_sl <= current_price:
                    return dynamic_sl, "dynamic"
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
        # Trigger slightly before the step target to account for slippage
        buffer = self.config.get("order_trigger_buffer_pct", 0.05) / 100
        effective_step = step_percent - buffer

        if side == "LONG":
            target_price = last_order_price * (1 + effective_step)
            return current_price >= target_price
        else:  # SHORT
            target_price = last_order_price * (1 - effective_step)
            return current_price <= target_price

    def is_stop_loss_hit(
        self,
        side: str,
        current_price: float,
        stop_loss: float,
        slippage_pct: float = 0.05
    ) -> bool:
        """Check if stop loss has been hit, with slippage buffer to avoid premature triggers"""
        if stop_loss == 0:
            return False

        # Add slippage buffer: require price to exceed SL by slippage_pct%
        # before triggering, to avoid noise/wick false triggers
        buffer = stop_loss * (slippage_pct / 100)

        if side == "LONG":
            return current_price <= (stop_loss - buffer)
        else:  # SHORT
            return current_price >= (stop_loss + buffer)

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

    def calculate_sl_percent(self, order_count: int) -> float:
        """
        SL percent to send to Cryptorg after each order:
        - Order 1: sl_initial (loss)
        - Order 2: 0 (breakeven)
        - Order 3+: sl_breakeven_plus (small profit)
        Positive value = loss side, negative = profit side for Cryptorg percentage event.
        """
        if order_count <= 1:
            return float(self.config["sl_initial"])
        if order_count == 2:
            if self.config.get("sl_breakeven_on_order2", True):
                return 0.0  # breakeven
            else:
                return float(self.config["sl_initial"])  # keep initial SL
        return -float(self.config.get("sl_after_order3", self.config.get("sl_breakeven_plus", 0.5)))

    def reset(self):
        """Reset position manager"""
        self.orders = []
