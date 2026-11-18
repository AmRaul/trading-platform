"""Тесты kandle-mcp на подставном API (без сети): python -m pytest services/mcp"""
import asyncio

import pytest

import kandle_mcp as km

BOTS = [
    {"id": 1, "name": "MRC DCA · BTC 15m Long · Консервативный", "symbol": "BTCUSDT", "side": "LONG",
     "exchange": "paper", "state": "SIGNAL", "total_pnl": 0.0,
     "config": {"bot_type": "dca", "order_count": 5, "step_percent": 1.55, "tp_percent": 0.97, "entry_size_usdt": 279.3}},
    {"id": 2, "name": "Шорт альтов · пирамидинг · 5 монет · Консервативный · SOLUSDT", "symbol": "SOLUSDT",
     "side": "SHORT", "exchange": "paper", "state": "PYRAMIDING", "total_pnl": 5.0,
     "config": {"bot_type": "pyramiding", "order_count": 4, "step_percent": 0.5, "tp_percent": 100},
     "open_position": {"id": 77, "average_price": 100.0, "current_sl": 102.0, "total_size": 500.0,
                       "order_count": 2, "unrealized_pnl": -3.5, "last_order_price": 99.5, "opened_at": "2026-11-20"}},
    {"id": 3, "name": "Шорт альтов · пирамидинг · 5 монет · Консервативный · ETHUSDT", "symbol": "ETHUSDT",
     "side": "SHORT", "exchange": "paper", "state": "SIGNAL", "total_pnl": 0.0,
     "config": {"bot_type": "pyramiding", "order_count": 4, "step_percent": 0.5, "tp_percent": 100}},
    {"id": 9, "name": "real", "symbol": "BTCUSDT", "side": "LONG", "exchange": "bybit", "state": "IDLE",
     "total_pnl": 0.0, "config": {}},
]
TRADES = [
    {"id": 1, "bot_id": 2, "position_id": 70, "symbol": "SOLUSDT", "side": "SHORT", "pnl": -2.0, "fees": 0.5,
     "total_orders": 1, "exit_reason": "SL_HIT"},
    {"id": 2, "bot_id": 2, "position_id": 71, "symbol": "SOLUSDT", "side": "SHORT", "pnl": 9.0, "fees": 1.5,
     "total_orders": 4, "exit_reason": "TRAILING_STOP"},
    {"id": 3, "bot_id": 2, "position_id": 72, "symbol": "SOLUSDT", "side": "SHORT", "pnl": -2.0, "fees": 0.5,
     "total_orders": 2, "exit_reason": "SL_HIT"},
    {"id": 4, "bot_id": 9, "position_id": 80, "symbol": "BTCUSDT", "side": "LONG", "pnl": 50.0, "fees": None,
     "total_orders": 1, "exit_reason": "TP_HIT"},
]
CTX = {"symbol": "SOLUSDT", "price": 98.0, "atr14": 4.0, "regime": "down"}


class FakeAPI:
    def __init__(self):
        self.posted = []

    async def get(self, path, **params):
        if path == "/api/bots/":
            return BOTS
        if path == "/api/analytics/trades":
            return TRADES
        if path == "/api/analytics/market-context":
            return {**CTX, "symbol": params["symbol"]}
        raise AssertionError(path)

    async def request(self, method, path, **kw):
        self.posted.append((method, path, kw["json"]))
        return {"id": 1, **kw["json"]}


@pytest.fixture(autouse=True)
def fake_api(monkeypatch):
    fake = FakeAPI()
    monkeypatch.setattr(km, "api", fake)
    return fake


def run(coro):
    return asyncio.run(coro)


def test_server_registers_tools_and_prompts():
    tools = {t.name for t in run(km.mcp.list_tools())}
    assert tools == {"bots_health", "list_bots", "get_trades", "portfolio_summary", "get_market_context",
                     "get_position_context", "log_review", "list_reviews"}
    prompts = {p.name for p in run(km.mcp.list_prompts())}
    assert prompts == {"health_check", "monthly_review", "second_opinion"}


def test_list_bots_filters_exchange():
    bots = run(km.list_bots(exchange="paper"))
    assert [b["bot_id"] for b in bots] == [1, 2, 3]
    assert bots[1]["open_position"]["id"] == 77


def test_portfolio_summary_groups_strategies_and_excludes_real():
    s = run(km.portfolio_summary(since="2026-11-18"))
    assert s["total"]["trades"] == 3  # сделка bybit-бота не попала
    assert s["total"]["pnl"] == 5.0 and s["total"]["fees"] == 2.5
    assert s["total"]["full_grid_trades"] == 1
    assert s["total"]["max_drawdown_closed"] == 2.0  # 9 → 7
    assert s["total"]["unrealized_pnl"] == -3.5
    short = s["strategies"]["Шорт альтов · пирамидинг · 5 монет · Консервативный"]
    assert len(short["bots"]) == 2 and short["trades"] == 3
    assert s["strategies"]["MRC DCA · BTC 15m Long · Консервативный"]["trades"] == 0
    assert short["exit_reasons"] == {"SL_HIT": 2, "TRAILING_STOP": 1}


def test_position_context_levels_for_short_pyramid():
    out = run(km.get_position_context(2))
    assert "forward_test" in out  # бумажный бот
    lv = out["levels_from_price"]
    assert lv["stop"] == {"price": 102.0, "pct": pytest.approx(4.08, abs=0.01), "atr": 1.0}
    # шорт-пирамида доливает по ходу движения — ниже последнего ордера
    assert lv["next_order"]["price"] == pytest.approx(99.5 * 0.995)
    assert "take_profit" not in lv  # tp 100 — без тейка


def test_second_opinion_requires_checkable_verdict(fake_api):
    with pytest.raises(km.ToolError):
        run(km.log_review("second_opinion", "x", bot_id=2, position_id=77, verdict={"action": "hold"}))
    v = {"action": "hold", "first_hit": "target", "confidence": 0.6, "key_risk": "дневка выше EMA50"}
    run(km.log_review("second_opinion", "разбор", bot_id=2, position_id=77, symbol="solusdt", verdict=v))
    method, path, body = fake_api.posted[-1]
    assert path == "/api/analytics/reviews" and body["symbol"] == "SOLUSDT" and body["verdict"] == v


def test_monthly_review_prompt_carries_expectations():
    text = km.monthly_review("2026-11-18", "2026-12-18")
    assert "15.8%" in text and "$2 140" in text and 'until="2026-12-18"' in text
