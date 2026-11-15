"""Стоп/тейк, отправляемые на биржу, совпадают со стопом бэкенда."""
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.adapters.bybit_executor import BybitExecutorAdapter
from app.domain.trading.entities import OrderInfo
from app.domain.trading.position_calculator import PositionCalculator

ALT_SHORT = {"bot_type": "pyramiding", "order_count": 4, "entry_size_usdt": 250, "step_percent": 0.5,
             "pyramiding_multiplier": 1.0, "sl_initial": 2.0, "sl_breakeven_on_order2": False,
             "sl_after_order3": 2.0, "use_trailing": True, "trailing_percent": 8.1, "tp_percent": 100.0}


def _calc(cfg, prices):
    c = PositionCalculator(cfg)
    for i, p in enumerate(prices, 1):
        c.add_order(OrderInfo(i, p, cfg["entry_size_usdt"]))
    return c


def _exchange_sl_price(c, side):
    avg, pct = c.calculate_average_price(c.orders), c.exchange_sl_percent(side)
    return avg * (1 - pct / 100) if side == "LONG" else avg * (1 + pct / 100)


def test_no_tp_when_tp_percent_100():
    c = _calc(ALT_SHORT, [100, 99.5, 99, 98.5])
    assert c.tp_percent_for_order(4) is None
    assert c.take_profit_price("SHORT") is None


def test_tp_still_sent_for_normal_values():
    assert _calc({**ALT_SHORT, "tp_percent": 3.0}, [100] * 4).tp_percent_for_order(4) == 3.0


@pytest.mark.parametrize("prices", [[100], [100, 99.5], [100, 99.5, 99], [100, 99.5, 99, 98.5]])
def test_short_exchange_stop_matches_backend_stop(prices):
    c = _calc(ALT_SHORT, prices)
    backend_sl, _ = c.calculate_stop_loss("SHORT", c.orders, prices[-1], trailing_enabled=False)
    assert c.exchange_sl_percent("SHORT") > 0  # стоп шорта выше средней
    assert _exchange_sl_price(c, "SHORT") == pytest.approx(backend_sl)


def test_long_breakeven_plus_is_negative():
    cfg = {**ALT_SHORT, "sl_breakeven_on_order2": True, "sl_breakeven_plus": 0.5}
    c = _calc(cfg, [100, 100.5])
    assert c.exchange_sl_percent("LONG") == pytest.approx(-0.5)


def _bybit(step="0.1", min_qty="0.1", tick="0.01"):
    a = BybitExecutorAdapter.__new__(BybitExecutorAdapter)
    a._testnet = True
    a._client = MagicMock()
    a._client.get_instruments_info.return_value = {"retCode": 0, "result": {"list": [
        {"lotSizeFilter": {"qtyStep": step, "minOrderQty": min_qty}, "priceFilter": {"tickSize": tick}}]}}
    BybitExecutorAdapter._instruments.clear()
    return a


@pytest.mark.asyncio
async def test_bybit_qty_rounded_down_to_step():
    qty, err = await _bybit()._qty_for_usdt("SOLUSDT", 25, 136.53)
    assert qty == "0.1" and not err  # 0.1831 → 0.1


@pytest.mark.asyncio
async def test_bybit_qty_below_min_lot_rejected():
    qty, err = await _bybit(step="0.01", min_qty="0.01")._qty_for_usdt("ETHUSDT", 25, 4000)
    assert qty is None and "минимального лота" in err


@pytest.mark.asyncio
async def test_bybit_price_rounded_to_tick():
    assert await _bybit(tick="0.001")._price_str("XRPUSDT", 0.61234567) == "0.612"
    assert Decimal(await _bybit(tick="0.5")._price_str("BTCUSDT", 60000.3)) == Decimal("60000.5")


def _hedge_bybit():
    a = _bybit(step="0.1", min_qty="0.1", tick="0.01")
    a._hedge = True
    a._client.get_tickers.return_value = {"retCode": 0, "result": {"list": [{"lastPrice": "100"}]}}
    a._client.place_order.return_value = {"retCode": 0, "result": {"orderId": "1"}}
    a._client.set_trading_stop.return_value = {"retCode": 0}
    a._client.get_positions.return_value = {"retCode": 0, "result": {"list": [
        {"positionIdx": 1, "side": "Buy", "size": "3", "avgPrice": "101"},
        {"positionIdx": 2, "side": "Sell", "size": "1", "avgPrice": "100"},
    ]}}
    return a


@pytest.mark.asyncio
async def test_bybit_hedge_orders_use_position_idx():
    a = _hedge_bybit()
    await a.open_position("SOLUSDT", "short", 100, 5, None, None)
    assert a._client.place_order.call_args.kwargs["positionIdx"] == 2
    await a.add_to_position("SOLUSDT", "long", 100)
    assert a._client.place_order.call_args.kwargs["positionIdx"] == 1


@pytest.mark.asyncio
async def test_bybit_hedge_close_takes_size_of_its_side():
    a = _hedge_bybit()
    await a.close_position("SOLUSDT", "SHORT")
    kw = a._client.place_order.call_args.kwargs
    assert kw["qty"] == "1.0" and kw["side"] == "Buy" and kw["positionIdx"] == 2 and kw["reduceOnly"]


@pytest.mark.asyncio
async def test_bybit_hedge_stop_from_side_avg():
    a = _hedge_bybit()
    await a.update_stop_and_tp("SOLUSDT", "long", 2.0, None)
    kw = a._client.set_trading_stop.call_args.kwargs
    assert kw["positionIdx"] == 1 and kw["stopLoss"] == "98.98"  # 101 × 0.98


@pytest.mark.asyncio
async def test_bybit_one_way_unchanged():
    a = _hedge_bybit()
    a._hedge = False
    await a.open_position("SOLUSDT", "long", 100, 5, None, None)
    assert a._client.place_order.call_args.kwargs["positionIdx"] == 0
