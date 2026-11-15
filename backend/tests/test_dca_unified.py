"""DCA ведёт бэкенд одинаково для любой биржи: страховочные через add_to_position,
TP/стоп ловятся по цене, позиция сверяется с биржей."""
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.trading.position_calculator import PositionCalculator
from app.domain.trading.entities import OrderInfo
from app.services.strategy import BotState, RECONCILE_INTERVAL_SEC
from tests.conftest import make_mock_bot, make_mock_position
from tests.test_strategy_engine import _make_engine

ENTRY = 50000.0
DCA_CONFIG = {
    "bot_type": "dca",
    "order_count": 5,          # вход + 4 страховочных
    "entry_size_usdt": 100,
    "step_percent": 1.55,
    "dca_multiplier": 2.0,
    "dca_multiplier_price": 1.0,
    "tp_percent": 0.97,
    "sl_initial": 20.0,
    "use_trailing": False,
    "trailing_percent": 1.5,
    "leverage": 10,
}


def calc_with_orders(n, config=None, side="LONG"):
    c = PositionCalculator(dict(config or DCA_CONFIG))
    price, size = ENTRY, 100.0
    for i in range(n):
        c.add_order(OrderInfo(i + 1, price, size))
        price = price * (1 - 0.0155) if side == "LONG" else price * (1 + 0.0155)
        size *= 2
    return c


# ── calculator ────────────────────────────────────────────────────────────────

def test_next_dca_level_is_step_from_previous_order():
    c = calc_with_orders(2)
    last = c.orders[-1].price
    assert c.next_dca_price("LONG") == pytest.approx(last * (1 - 0.0155))
    assert not c.should_add_dca_order("LONG", last * (1 - 0.015))
    assert c.should_add_dca_order("LONG", last * (1 - 0.0156))


def test_next_dca_level_short():
    c = calc_with_orders(1, side="SHORT")
    assert c.next_dca_price("SHORT") == pytest.approx(ENTRY * 1.0155)
    assert c.should_add_dca_order("SHORT", ENTRY * 1.016)


def test_dca_price_step_multiplier():
    c = calc_with_orders(3, {**DCA_CONFIG, "dca_multiplier_price": 1.5})
    # 3 ордера = вход + 2 страховочных → следующий шаг 1.55% × 1.5²
    assert c.next_dca_price("LONG") == pytest.approx(c.orders[-1].price * (1 - 0.0155 * 2.25))


def test_no_dca_when_grid_full():
    c = calc_with_orders(5)
    assert c.is_grid_full()
    assert c.next_dca_price("LONG") is None
    assert not c.should_add_dca_order("LONG", 1.0)


def test_dca_order_sizes_martingale():
    c = calc_with_orders(3)
    assert c.calculate_next_order_size() == pytest.approx(800.0)


def test_dca_stop_only_after_full_grid_from_average():
    partial = calc_with_orders(4)
    assert partial.calculate_stop_loss("LONG", partial.orders, ENTRY) == (0.0, "disabled")
    assert partial.calculate_sl_percent(4) is None

    full = calc_with_orders(5)
    avg = full.calculate_average_price(full.orders)
    sl, sl_type = full.calculate_stop_loss("LONG", full.orders, ENTRY)
    assert sl == pytest.approx(avg * 0.8)
    assert sl_type == "dca"
    assert full.calculate_sl_percent(5) == 20.0


def test_dca_stop_disabled_when_sl_none():
    full = calc_with_orders(5, {**DCA_CONFIG, "sl_initial": None})
    assert full.calculate_stop_loss("LONG", full.orders, ENTRY) == (0.0, "disabled")
    assert full.calculate_sl_percent(5) is None


def test_dca_tp_on_every_order_from_average():
    c = calc_with_orders(3)
    assert c.tp_percent_for_order(1) == 0.97
    assert c.tp_percent_for_order(3) == 0.97
    avg = c.calculate_average_price(c.orders)
    assert c.take_profit_price("LONG") == pytest.approx(avg * 1.0097)
    assert c.is_take_profit_hit("LONG", avg * 1.0098)
    assert not c.is_take_profit_hit("LONG", avg * 1.009)


def test_pyramiding_tp_only_on_last_order():
    cfg = {"bot_type": "pyramiding", "order_count": 3, "tp_percent": 3.0,
           "entry_size_usdt": 100, "pyramiding_multiplier": 1.5, "step_percent": 2}
    c = PositionCalculator(cfg)
    c.add_order(OrderInfo(1, ENTRY, 100))
    assert c.tp_percent_for_order(1) is None
    assert c.take_profit_price("LONG") is None
    c.add_order(OrderInfo(2, ENTRY * 1.02, 150))
    c.add_order(OrderInfo(3, ENTRY * 1.04, 225))
    assert c.tp_percent_for_order(3) == 3.0
    assert c.take_profit_price("LONG") is not None


# ── engine ────────────────────────────────────────────────────────────────────

def _dca_engine(n_orders=1, exchange_size=None):
    bot = make_mock_bot(config=dict(DCA_CONFIG), state="PYRAMIDING")
    pos = make_mock_position(average_price=ENTRY, total_size=100.0, current_sl=0.0)
    pos.trailing_enabled = False
    db = AsyncMock()
    db.add = MagicMock()
    engine, executor, market_data, publisher = _make_engine(bot, pos, db)
    executor.get_open_position_size = AsyncMock(return_value=exchange_size)
    c = calc_with_orders(n_orders)
    engine.calculator = c
    pos.average_price = c.calculate_average_price(c.orders)
    pos.total_size = c.get_total_size()
    pos.order_count = n_orders
    return engine, bot, pos, executor, market_data


@pytest.mark.asyncio
async def test_open_dca_sends_only_entry_with_tp():
    bot = make_mock_bot(config=dict(DCA_CONFIG), state="IDLE")
    db = AsyncMock()
    db.add = MagicMock()
    engine, executor, *_ = _make_engine(bot, None, db)
    result = await engine.manual_entry()
    assert result["success"]
    kwargs = executor.open_position.call_args.kwargs
    assert "dca_config" not in kwargs
    assert kwargs["tp_percent"] == 0.97
    assert kwargs["sl_percent"] is None  # стоп только после полной сетки


@pytest.mark.asyncio
async def test_price_drop_places_safety_order_via_executor():
    engine, bot, pos, executor, market_data = _dca_engine(n_orders=1)
    level = ENTRY * (1 - 0.0155)
    market_data.get_ticker = AsyncMock(return_value={"lastPrice": str(level)})
    await engine.on_price_update(level * 0.9999)
    executor.add_to_position.assert_awaited_once()
    assert executor.add_to_position.call_args.kwargs["amount_usdt"] == pytest.approx(200.0)
    assert len(engine.calculator.orders) == 2
    # TP пересчитан от новой средней и отправлен на биржу
    assert executor.update_stop_and_tp.call_args.kwargs["tp_percent"] == 0.97


@pytest.mark.asyncio
async def test_tp_hit_closes_position_on_any_exchange():
    engine, bot, pos, executor, _ = _dca_engine(n_orders=3)
    tp = engine.calculator.take_profit_price("LONG")
    await engine.on_price_update(tp * 1.0001)
    executor.close_position.assert_awaited_once()
    assert engine.current_state == BotState.IDLE
    assert bot.state == "IDLE"


@pytest.mark.asyncio
async def test_full_grid_stop_closes_position():
    engine, bot, pos, executor, _ = _dca_engine(n_orders=5)
    sl, _ = engine.calculator.calculate_stop_loss("LONG", engine.calculator.orders, ENTRY)
    pos.current_sl = sl
    await engine.on_price_update(sl * 0.99)
    executor.close_position.assert_awaited_once()
    assert engine.current_state == BotState.IDLE


@pytest.mark.asyncio
async def test_reconcile_closes_when_exchange_has_no_position():
    engine, bot, pos, executor, _ = _dca_engine(n_orders=2, exchange_size=0.0)
    engine._last_reconcile = time.time() - RECONCILE_INTERVAL_SEC - 1
    await engine.on_price_update(ENTRY * 0.99)
    executor.close_position.assert_not_awaited()  # на бирже уже закрыто
    assert engine.current_state == BotState.IDLE
    assert bot.state == "IDLE"


@pytest.mark.asyncio
async def test_reconcile_keeps_position_when_exchange_has_it():
    engine, bot, pos, executor, _ = _dca_engine(n_orders=2, exchange_size=0.01)
    engine._last_reconcile = time.time() - RECONCILE_INTERVAL_SEC - 1
    await engine.on_price_update(ENTRY * 0.99)
    assert engine.current_state == BotState.PYRAMIDING


@pytest.mark.asyncio
async def test_reconcile_skipped_when_exchange_cannot_report():
    engine, bot, pos, executor, _ = _dca_engine(n_orders=2, exchange_size=None)  # Cryptorg
    engine._last_reconcile = time.time() - RECONCILE_INTERVAL_SEC - 1
    await engine.on_price_update(ENTRY * 0.99)
    executor.get_open_position_size.assert_awaited_once()
    assert engine.current_state == BotState.PYRAMIDING


@pytest.mark.asyncio
async def test_reconcile_throttled():
    engine, bot, pos, executor, _ = _dca_engine(n_orders=2, exchange_size=0.0)
    await engine.on_price_update(ENTRY * 0.99)
    executor.get_open_position_size.assert_not_awaited()
    assert engine.current_state == BotState.PYRAMIDING
