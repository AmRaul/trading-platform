import pytest
from app.services.position_manager import PositionManager, OrderInfo
from tests.conftest import make_bot_config


def pm(extra_config=None):
    return PositionManager(make_bot_config(**(extra_config or {})))


# ── calculate_average_price ──────────────────────────────────────────────────

def test_average_price_single_order():
    p = pm()
    p.add_order(OrderInfo(1, 50000.0, 100.0))
    assert p.calculate_average_price(p.orders) == 50000.0


def test_average_price_two_orders():
    p = pm()
    p.add_order(OrderInfo(1, 50000.0, 100.0))
    p.add_order(OrderInfo(2, 52000.0, 150.0))
    # (50000*100 + 52000*150) / 250 = (5_000_000 + 7_800_000) / 250 = 51200
    avg = p.calculate_average_price(p.orders)
    assert avg == pytest.approx(51200.0)


def test_average_price_empty():
    p = pm()
    assert p.calculate_average_price([]) == 0.0


# ── calculate_next_order_size ────────────────────────────────────────────────

def test_first_order_size():
    p = pm()
    assert p.calculate_next_order_size() == 100.0


def test_second_order_size():
    p = pm()
    p.add_order(OrderInfo(1, 50000.0, 100.0))
    assert p.calculate_next_order_size() == pytest.approx(150.0)  # 100 * 1.5


def test_third_order_size():
    p = pm()
    p.add_order(OrderInfo(1, 50000.0, 100.0))
    p.add_order(OrderInfo(2, 51000.0, 150.0))
    assert p.calculate_next_order_size() == pytest.approx(225.0)  # 150 * 1.5


# ── calculate_stop_loss ──────────────────────────────────────────────────────

def test_initial_sl_long():
    p = pm()
    p.add_order(OrderInfo(1, 50000.0, 100.0))
    sl, sl_type = p.calculate_stop_loss("LONG", p.orders, 50000.0)
    # 50000 * (1 - 0.03) = 48500
    assert sl == pytest.approx(48500.0)
    assert sl_type == "initial"


def test_initial_sl_short():
    p = pm()
    p.add_order(OrderInfo(1, 50000.0, 100.0))
    sl, sl_type = p.calculate_stop_loss("SHORT", p.orders, 50000.0)
    # 50000 * (1 + 0.03) = 51500
    assert sl == pytest.approx(51500.0)
    assert sl_type == "initial"


def test_breakeven_sl_two_orders_default():
    # sl_breakeven_on_order2 defaults to True — order 2 moves SL to breakeven
    # plus sl_breakeven_plus (default 0.5%) so commissions are covered.
    # avg=51200 → 51200 * 1.005 = 51456
    p = pm()
    p.add_order(OrderInfo(1, 50000.0, 100.0))
    p.add_order(OrderInfo(2, 52000.0, 150.0))
    sl, sl_type = p.calculate_stop_loss("LONG", p.orders, 52000.0)
    assert sl == pytest.approx(51456.0)
    assert sl_type == "dynamic"


def test_dynamic_sl_long_two_orders():
    p = pm({"sl_breakeven_on_order2": False})
    p.add_order(OrderInfo(1, 50000.0, 100.0))
    p.add_order(OrderInfo(2, 52000.0, 150.0))
    # breakeven disabled on order 2 falls back to the "initial" branch —
    # sl_initial (3%) off the first order's entry price, not avg_price.
    # 50000 * (1 - 0.03) = 48500
    sl, sl_type = p.calculate_stop_loss("LONG", p.orders, 52000.0)
    assert sl == pytest.approx(48500.0)
    assert sl_type == "initial"


def test_dynamic_sl_short_two_orders():
    p = pm({"sl_breakeven_on_order2": False})
    p.add_order(OrderInfo(1, 50000.0, 100.0))
    p.add_order(OrderInfo(2, 48000.0, 150.0))
    # 50000 * (1 + 0.03) = 51500
    sl, sl_type = p.calculate_stop_loss("SHORT", p.orders, 48000.0)
    assert sl == pytest.approx(51500.0)
    assert sl_type == "initial"


def test_trailing_sl_activates_long():
    p = pm({"use_trailing": True, "trailing_percent": 1.5})
    p.add_order(OrderInfo(1, 50000.0, 100.0))
    p.add_order(OrderInfo(2, 52000.0, 150.0))
    # avg=51200, dynamic_sl=51456 (breakeven + 0.5%)
    # current_price=55000, trailing_sl = 55000*(1-0.015) = 54175
    # LONG: max(51456, 54175) = 54175 → trailing wins
    sl, sl_type = p.calculate_stop_loss("LONG", p.orders, 55000.0)
    assert sl == pytest.approx(54175.0)
    assert sl_type == "trailing"


def test_trailing_sl_dynamic_wins_when_price_below_avg():
    p = pm({"use_trailing": True, "trailing_percent": 1.5})
    p.add_order(OrderInfo(1, 50000.0, 100.0))
    p.add_order(OrderInfo(2, 52000.0, 150.0))
    # avg=51200, dynamic_sl=51200*1.005=51456 (breakeven + sl_breakeven_plus)
    # current_price=51600, trailing_sl = 51600*(1-0.015) = 50826
    # LONG: max(51456, 50826) = 51456 → dynamic (breakeven) wins
    sl, sl_type = p.calculate_stop_loss("LONG", p.orders, 51600.0)
    assert sl == pytest.approx(51456.0)
    assert sl_type == "dynamic"


# ── should_add_order ─────────────────────────────────────────────────────────

def test_should_add_order_long_not_yet():
    p = pm()
    p.add_order(OrderInfo(1, 50000.0, 100.0))
    # need +2% = 51000, current only 50500
    assert p.should_add_order("LONG", 50500.0, 50000.0) is False


def test_should_add_order_long_reached():
    p = pm()
    p.add_order(OrderInfo(1, 50000.0, 100.0))
    # need 51000, current 51000 — exactly at threshold
    assert p.should_add_order("LONG", 51000.0, 50000.0) is True


def test_should_add_order_short_reached():
    p = pm()
    p.add_order(OrderInfo(1, 50000.0, 100.0))
    # need 50000*(1-0.02) = 49000
    assert p.should_add_order("SHORT", 49000.0, 50000.0) is True


def test_should_add_order_max_orders_reached():
    p = pm()
    for i in range(3):
        p.add_order(OrderInfo(i + 1, 50000.0 + i * 1000, 100.0))
    assert p.should_add_order("LONG", 55000.0, p.get_last_order_price()) is False


# ── is_stop_loss_hit ─────────────────────────────────────────────────────────

def test_sl_hit_long():
    p = pm()
    assert p.is_stop_loss_hit("LONG", 48000.0, 48500.0) is True


def test_sl_not_hit_long():
    p = pm()
    assert p.is_stop_loss_hit("LONG", 49000.0, 48500.0) is False


def test_sl_hit_short():
    p = pm()
    assert p.is_stop_loss_hit("SHORT", 51600.0, 51500.0) is True


def test_sl_not_hit_short():
    p = pm()
    assert p.is_stop_loss_hit("SHORT", 51000.0, 51500.0) is False


def test_sl_zero_never_hit():
    p = pm()
    assert p.is_stop_loss_hit("LONG", 0.0, 0.0) is False


# ── calculate_unrealized_pnl ─────────────────────────────────────────────────
# total_size is the position's notional value in USDT (not coin quantity),
# so PnL = total_size * (%price move) — see position_calculator.py.

def test_pnl_long_profit():
    p = pm()
    # avg=50000, current=51000, size=100 USDT notional
    # 100 * (51000-50000)/50000 = 100 * 0.02 = 2.0
    pnl = p.calculate_unrealized_pnl("LONG", 50000.0, 51000.0, 100.0)
    assert pnl == pytest.approx(2.0)


def test_pnl_long_loss():
    p = pm()
    # 100 * (49000-50000)/50000 = 100 * -0.02 = -2.0
    pnl = p.calculate_unrealized_pnl("LONG", 50000.0, 49000.0, 100.0)
    assert pnl == pytest.approx(-2.0)


def test_pnl_short_profit():
    p = pm()
    # 100 * (50000-49000)/50000 = 100 * 0.02 = 2.0
    pnl = p.calculate_unrealized_pnl("SHORT", 50000.0, 49000.0, 100.0)
    assert pnl == pytest.approx(2.0)
