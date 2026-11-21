"""Уведомления в Telegram, уровни позиции, what_changed, комплекты форвард-теста, обзор счёта."""
import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.monitoring.position_levels import position_levels
from app.application.monitoring.what_changed import bot_snapshot, diff
from app.domain import forward_test as ft
from app.domain.trading.entities import OrderInfo
from app.services.telegram_notifier import TelegramNotifier, format_event
from tests.conftest import make_bot_config


# --- Telegram ---------------------------------------------------------------

def test_format_entry_add_exit():
    opened = format_event("position_opened", {"side": "SHORT", "symbol": "SOLUSDT", "price": 73.06, "size": 250,
                                              "sl": 74.52}, "Шорт SOL", "paper", 4)
    assert opened.startswith("📝 🟢 Вход · Шорт SOL") and "@ 73.06" in opened and "250$" in opened

    add = format_event("pyramiding_order_added", {"side": "SHORT", "symbol": "SOLUSDT", "order_number": 3,
                                                  "price": 72.5, "new_average_price": 72.9, "new_sl": 74.3,
                                                  "unrealized_pnl": 1.5}, "Шорт SOL", "cryptorg", 4)
    assert add.startswith("➕ Ордер #3/4") and "+1.50$" in add  # реальный — без пометки paper

    win = format_event("position_closed", {"side": "SHORT", "symbol": "SOLUSDT", "exit_price": 68.68,
                                           "exit_reason": "TP_HIT", "pnl": 59.04, "pnl_percent": 6.01,
                                           "total_orders": 4}, "Шорт SOL", "cryptorg", 4)
    assert win.startswith("✅ Выход (тейк)") and "+59.04$ (+6.01%)" in win
    loss = format_event("position_closed", {"exit_reason": "STRADDLE_TRAILING_STOP", "pnl": -3.0}, "S", "bybit", None)
    assert loss.startswith("🔴 Выход (трейлинг)")
    assert format_event("trailing_stop_moved", {}, "x", "paper", 4) is None  # слишком часто — не шлём


def _u(**kw):
    base = dict(id=1, username="me", is_active=True, approved=True, telegram_chat_id=None, telegram_notify="all")
    return SimpleNamespace(**{**base, **kw})


def test_route_per_user():
    n = TelegramNotifier("t", "owner-chat", "all", owner="me")
    assert n.route_for(_u()) == ("owner-chat", "all")  # владелец без своей привязки — общий чат
    assert n.route_for(_u(telegram_chat_id="42")) == ("42", "all")  # своя привязка важнее
    assert n.route_for(_u(username="anna")) is None  # чужой без привязки — никуда, не в чат владельца
    assert n.route_for(_u(username="anna", telegram_chat_id="77", telegram_notify="real")) == ("77", "real")
    assert n.route_for(_u(username="anna", telegram_chat_id="77", approved=False)) is None
    assert n.route_for(_u(username="anna", telegram_chat_id="77", is_active=False)) is None
    assert n.route_for(_u(username="anna", telegram_chat_id="77", telegram_notify="off")) is None
    assert TelegramNotifier("t", "c", "real", owner="me").route_for(_u()) == ("c", "real")  # глобально real
    assert TelegramNotifier("", "c", "all", owner="me").enabled is False


@pytest.mark.asyncio
async def test_event_goes_to_bot_owner_chat_and_respects_mode():
    n = TelegramNotifier("t", "owner-chat", "all", owner="me")
    n.send = AsyncMock(return_value=True)
    n._bot_info = AsyncMock(return_value=("бот Анны", "cryptorg", 4, 2))
    n._route = AsyncMock(return_value=("77", "all"))
    await n._send_event("position_closed", {"bot_id": 5, "pnl": 1.0})
    assert n.send.await_args.args[1] == "77"

    n.send.reset_mock()
    n._bot_info = AsyncMock(return_value=("бумажный", "paper", 4, 2))
    n._route = AsyncMock(return_value=("77", "real"))
    await n._send_event("position_closed", {"bot_id": 6, "pnl": 1.0})
    n.send.assert_not_awaited()

    n._route = AsyncMock(return_value=None)  # не привязал Telegram
    await n._send_event("position_closed", {"bot_id": 6, "pnl": 1.0})
    n.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_does_not_wait_for_telegram():
    """Торговый цикл не ждёт Telegram: notify возвращается сразу, отправка — отдельной задачей."""
    n = TelegramNotifier("t", "c", "all", owner="me")
    n._bot_info = AsyncMock(return_value=("b", "paper", 4, 1))
    n._route = AsyncMock(return_value=("c", "all"))
    started = asyncio.Event()

    async def slow_send(text, chat):
        started.set()
        await asyncio.sleep(10)

    n.send = slow_send
    n.notify("position_opened", {"bot_id": 1, "side": "LONG", "symbol": "BTCUSDT", "price": 1, "size": 1})
    assert len(n._tasks) == 1
    await asyncio.wait_for(started.wait(), 1)
    for t in n._tasks:
        t.cancel()


# --- уровни позиции ---------------------------------------------------------

def _short_cfg(**kw):
    return make_bot_config(**{"order_count": 4, "step_percent": 0.5, "pyramiding_multiplier": 1.0,
                              "sl_initial": 2.0, "sl_after_order3": 2.0, "use_trailing": True,
                              "trailing_percent": 5.0, "tp_percent": 6.0, **kw})


def test_levels_full_grid_short_with_trailing_and_take():
    orders = [OrderInfo(i + 1, p, 250) for i, p in enumerate([100.0, 99.5, 99.0, 98.5])]
    avg = sum(o.price for o in orders) / 4  # равные доборы — средняя арифметическая
    lv = position_levels(_short_cfg(), "SHORT", orders, current_sl=avg * 1.02, price=97.0, total_size=1000)
    assert lv["orders"] == "4/4" and lv["next_order"] is None
    assert lv["stop"]["in_profit"] is False and lv["stop"]["net_usdt"] < -20  # −2% от 1000 и комиссия
    assert lv["take_profit"]["price"] == pytest.approx(avg * 0.94)
    assert lv["take_profit"]["net_usdt"] == pytest.approx(60 - lv["take_profit"]["fees_usdt"], abs=0.01)
    # трейлинг двинет стоп, когда price*(1+5%) станет ниже текущего стопа
    assert lv["trailing"]["moves_stop_from_price"] == pytest.approx(avg * 1.02 / 1.05)
    assert lv["trailing"]["moving_now"] is False


def test_levels_first_order_explains_trailing_and_take():
    lv = position_levels(_short_cfg(), "SHORT", [OrderInfo(1, 100.0, 250)], current_sl=102.0, price=100.0,
                         total_size=250)
    assert lv["trailing"]["active"] is False and "2-го ордера" in lv["trailing"]["note"]
    assert lv["take_profit"]["price"] is None and "4-го ордера" in lv["take_profit"]["note"]
    nxt = lv["next_order"]
    assert nxt["number"] == 2 and nxt["price"] == pytest.approx(99.5) and nxt["size_usdt"] == 250
    assert nxt["stop_after"]["type"] in ("dynamic", "trailing")


def test_levels_without_take_profit():
    lv = position_levels(_short_cfg(tp_percent=100), "SHORT",
                         [OrderInfo(1, 100.0, 250)], 102.0, 100.0, 250)
    assert "тейка нет" in lv["take_profit"]["note"]


# --- what_changed -----------------------------------------------------------

def _bot(id, state="PYRAMIDING", total=0.0, name=None):
    return SimpleNamespace(id=id, name=name or f"bot{id}", symbol="SOLUSDT", side="SHORT", exchange="paper",
                           state=state, total_pnl=total)


def _pos(id, sl, pnl, orders=4):
    return SimpleNamespace(id=id, current_sl=sl, unrealized_pnl=pnl, order_count=orders)


def test_diff_finds_stop_moves_pnl_states_added_removed():
    old = {"1": bot_snapshot(_bot(1), _pos(10, 74.0, 5.0)), "2": bot_snapshot(_bot(2, "SIGNAL")),
           "3": bot_snapshot(_bot(3, "SIGNAL"))}
    new = {"1": bot_snapshot(_bot(1), _pos(10, 72.0, 25.0), live={"unrealized_pnl": 30.0}),
           "2": bot_snapshot(_bot(2, "PYRAMIDING"), _pos(11, 75.0, 0.0, 1)),
           "4": bot_snapshot(_bot(4, "SIGNAL"))}
    d = diff(old, new)
    assert d["bots_added"] == [{"bot_id": 4, "name": "bot4"}]
    assert d["bots_removed"] == [{"bot_id": 3, "name": "bot3"}]
    assert d["state_changes"] == [{"bot_id": 2, "name": "bot2", "from": "SIGNAL", "to": "PYRAMIDING"}]
    assert [m["bot_id"] for m in d["stop_moves"]] == [1] and d["stop_moves"][0]["to"] == 72.0
    assert d["unrealized_changes"][0]["change"] == 25.0  # live из Redis важнее БД
    assert d["totals"]["unrealized_pnl"]["change"] == 25.0


def test_diff_new_position_is_not_a_stop_move():
    old = {"1": bot_snapshot(_bot(1), _pos(10, 74.0, 5.0))}
    new = {"1": bot_snapshot(_bot(1), _pos(11, 70.0, 0.0))}  # закрылась и открылась заново
    assert diff(old, new)["stop_moves"] == []


# --- комплекты форвард-теста ----------------------------------------------------

def test_forward_test_values_and_parse():
    assert set(ft.valid_values()) == {"portfolio/mrc", "portfolio/short", "take6/short"}
    assert ft.parse("portfolio/short") == ("portfolio", "short")
    assert ft.parse("portfolio/xxx") is None and ft.parse("take6") is None and ft.parse(None) is None


NAMES = {
    "MRC DCA · BTC 15m Long · Консервативный": "portfolio/mrc",
    "Шорт альтов · пирамидинг · 5 монет · Консервативный · SOLUSDT": "portfolio/short",
    "Шорт альтов · пирамидинг · 5 монет · Тейк 6% · XRPUSDT": "take6/short",
    "HYPEUSDT": None,
}


def test_names_map_to_sets_and_migration_rules_agree():
    """Миграция размечает по своим LIKE-правилам — они должны давать то же, что from_bot_name."""
    src = (Path(__file__).parent.parent / "alembic" / "versions" / "a7b8c9d0e1f2_add_forward_test_to_bots.py").read_text()
    rules = re.findall(r'\("([^"]+)", "([^"]+)"\)', src)

    def like(pattern, name):
        rx = "^" + "".join(".*" if ch == "%" else re.escape(ch) for ch in pattern) + "$"
        return re.match(rx, name) is not None

    for name, expected in NAMES.items():
        assert ft.from_bot_name(name, "paper") == expected
        by_migration = next((v for p, v in rules if like(p, name)), None)
        assert by_migration == expected, name
    assert ft.from_bot_name("MRC DCA · BTC 15m Long · Консервативный", "cryptorg") is None


def test_bot_update_validates_forward_test():
    from app.schemas.bot import BotUpdate
    assert BotUpdate(forward_test="take6/short").forward_test == "take6/short"
    assert BotUpdate(forward_test="").forward_test == ""  # снять с теста
    with pytest.raises(ValueError):
        BotUpdate(forward_test="nope/x")


# --- обзор счёта через Bybit ------------------------------------------------------

@pytest.mark.asyncio
async def test_account_overview_maps_sides_and_pages():
    from app.adapters.bybit_executor import BybitExecutorAdapter
    ex = BybitExecutorAdapter.__new__(BybitExecutorAdapter)
    client = MagicMock()
    client.get_positions.return_value = {"retCode": 0, "result": {"list": [
        {"symbol": "SOLUSDT", "side": "Sell", "size": "3.4", "avgPrice": "73.5", "markPrice": "70",
         "positionValue": "250", "unrealisedPnl": "11.9", "leverage": "10", "liqPrice": "", "stopLoss": "75",
         "takeProfit": "", "createdTime": "1700000000000"},
        {"symbol": "ETHUSDT", "side": "", "size": "0", "avgPrice": "0"},
    ]}}
    pages = [
        {"retCode": 0, "result": {"list": [{"symbol": "SOLUSDT", "side": "Buy", "qty": "3", "avgEntryPrice": "74",
                                            "avgExitPrice": "70", "cumEntryValue": "222", "closedPnl": "11.5",
                                            "updatedTime": "1700000100000"}], "nextPageCursor": "p2"}},
        {"retCode": 0, "result": {"list": [{"symbol": "BTCUSDT", "side": "Sell", "qty": "0.01", "avgEntryPrice": "60000",
                                            "avgExitPrice": "61000", "cumEntryValue": "600", "closedPnl": "9.6",
                                            "updatedTime": "1700000200000"}], "nextPageCursor": ""}},
    ]
    client.get_closed_pnl.side_effect = lambda **kw: pages.pop(0) if pages else {"retCode": 0, "result": {"list": []}}
    ex._client = client
    ex._run = AsyncMock(side_effect=lambda fn: fn())

    out = await ex.account_overview(days=7, now_ms=1700000300000)
    assert out["ok"] and [p["symbol"] for p in out["positions"]] == ["SOLUSDT"]
    assert out["positions"][0]["side"] == "SHORT" and out["positions"][0]["liq_price"] is None
    # side закрытой сделки — сторона закрывающего ордера: Buy закрыл шорт, Sell — лонг
    assert [(c["symbol"], c["side"]) for c in out["closed"]] == [("BTCUSDT", "LONG"), ("SOLUSDT", "SHORT")]
    assert client.get_closed_pnl.call_args_list[1].kwargs["cursor"] == "p2"


@pytest.mark.asyncio
async def test_account_overview_api_error():
    from app.adapters.bybit_executor import BybitExecutorAdapter
    ex = BybitExecutorAdapter.__new__(BybitExecutorAdapter)
    ex._client = MagicMock()
    ex._run = AsyncMock(side_effect=RuntimeError("Invalid api key"))
    out = await ex.account_overview()
    assert out == {"ok": False, "error": "Invalid api key"}
