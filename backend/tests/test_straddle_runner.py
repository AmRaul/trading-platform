"""StraddleRunner: реальная пара LONG+SHORT на бирже, решения калькулятора → биржа и БД."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import Position, Trade
from app.schemas.bot import BotCreate, StrategyConfig
from app.services.straddle_runner import StraddleRunner

CFG = {"bot_type": "straddle", "entry_size_usdt": 100, "step_percent": 2.0, "order_count": 4,
       "pyramiding_multiplier": 1.0, "phase2_after_steps": 3, "add_stop_steps": 1.0,
       "trailing_percent": 5.0, "tp_percent": 100, "time_stop_minutes": 240, "max_rearms": 1,
       "leverage": 5, "cycle": False}


def _engine(cfg=CFG, state="IDLE", runtime_state=None, price=100.0):
    bot = SimpleNamespace(id=1, symbol="SOLUSDT", side="NEUTRAL", config=cfg, state=state,
                          runtime_state=runtime_state, total_pnl=0.0, started_at=None, stopped_at=None)
    ok = {"success": True, "orderId": "x"}
    ex = SimpleNamespace(open_position=AsyncMock(return_value=ok), add_to_position=AsyncMock(return_value=ok),
                         close_position=AsyncMock(return_value=ok), update_stop_and_tp=AsyncMock(return_value=ok),
                         get_open_position_size=AsyncMock(return_value=None))
    market = MagicMock()
    market.price = price
    market.get_ticker = AsyncMock(side_effect=lambda s: {"lastPrice": str(market.price)})
    db = MagicMock()
    db.add, db.commit, db.flush, db.rollback = MagicMock(), AsyncMock(), AsyncMock(), AsyncMock()
    return SimpleNamespace(bot=bot, db=db, position=None, _executor=ex, _market=market,
                           _publisher=SimpleNamespace(publish=AsyncMock()))


async def tick(r, price):
    r.engine._market.price = price
    await r.on_price(price)


def added(eng, cls):
    return [c.args[0] for c in eng.db.add.call_args_list if isinstance(c.args[0], cls)]


def opened_sides(eng):
    return [c.kwargs["side"] for c in eng._executor.open_position.await_args_list]


async def launched(cfg=CFG):
    eng = _engine(cfg)
    r = StraddleRunner(eng)
    res = await r.launch()
    assert res["success"] and res["opened"] == ["LONG", "SHORT"]
    return eng, r


@pytest.mark.asyncio
async def test_launch_opens_long_and_short():
    eng, r = await launched()
    assert opened_sides(eng) == ["long", "short"]
    kw = eng._executor.open_position.await_args.kwargs
    assert kw["order_volume_usdt"] == 100 and kw["sl_percent"] is None and kw["tp_percent"] is None
    assert [p.side for p in added(eng, Position)] == ["LONG", "SHORT"]
    assert eng.bot.state == "STRADDLE" and eng.bot.runtime_state["anchor"] == 100.0


@pytest.mark.asyncio
async def test_launch_fails_when_exchange_rejects_both():
    eng = _engine()
    eng._executor.open_position.return_value = {"success": False, "error": "x"}
    r = StraddleRunner(eng)
    res = await r.launch()
    assert not res["success"] and eng.bot.state == "IDLE"


@pytest.mark.asyncio
async def test_bybit_switches_to_hedge_mode():
    eng = _engine()
    eng._executor.ensure_hedge_mode = AsyncMock(return_value={"success": True})
    r = StraddleRunner(eng)
    await r.launch()
    eng._executor.ensure_hedge_mode.assert_awaited_once_with("SOLUSDT")


@pytest.mark.asyncio
async def test_winner_adds_loser_untouched_then_phase2():
    eng, r = await launched()
    await tick(r, 102)
    await tick(r, 104)
    adds = eng._executor.add_to_position.await_args_list
    assert [c.kwargs["side"] for c in adds] == ["long", "long"]
    assert r.positions["LONG"].order_count == 3 and r.positions["SHORT"].order_count == 1
    await tick(r, 106)
    closed = eng._executor.close_position.await_args_list
    assert [c.kwargs["side"] for c in closed] == ["SHORT"]
    trade = added(eng, Trade)[-1]
    assert trade.exit_reason == "STRADDLE_PHASE2" and trade.pnl == pytest.approx(-6)
    assert "SHORT" not in r.positions and r.state.phase == 2


@pytest.mark.asyncio
async def test_whipsaw_closes_long_and_reopens_it():
    eng, r = await launched()
    await tick(r, 102)
    await tick(r, 100)
    assert [c.kwargs["side"] for c in eng._executor.close_position.await_args_list] == ["LONG"]
    assert opened_sides(eng) == ["long", "short", "long"]         # пара снова открыта
    assert added(eng, Trade)[-1].exit_reason == "STRADDLE_WHIPSAW"
    assert r.state.rearms == 1 and eng.bot.state == "STRADDLE"


@pytest.mark.asyncio
async def test_time_stop_closes_both_and_finishes():
    eng, r = await launched()
    r.state.started_at -= 241 * 60
    await tick(r, 100.5)
    assert [c.kwargs["side"] for c in eng._executor.close_position.await_args_list] == ["LONG", "SHORT"]
    assert eng.bot.state == "IDLE" and r.state.exit_reason == "TIME_STOP"
    from app.services.websocket import price_stream_manager
    price_stream_manager.unregister_strategy.assert_called_with(1)


@pytest.mark.asyncio
async def test_max_rearms_closes_remaining_side():
    eng, r = await launched({**CFG, "max_rearms": 0})
    await tick(r, 102)
    await tick(r, 100)
    assert [c.kwargs["side"] for c in eng._executor.close_position.await_args_list] == ["LONG", "SHORT"]
    assert eng.bot.state == "IDLE" and r.state.exit_reason == "MAX_REARMS"


@pytest.mark.asyncio
async def test_manual_close_closes_both():
    eng, r = await launched()
    eng._market.price = 101
    res = await r.manual_close()
    assert res["success"] and eng.bot.state == "IDLE"
    assert {t.exit_reason for t in added(eng, Trade)} == {"STRADDLE_MANUAL_CLOSE"}


@pytest.mark.asyncio
async def test_restore_continues_from_runtime_state():
    eng, r = await launched()
    await tick(r, 102)
    eng2 = _engine(state="STRADDLE", runtime_state=dict(eng.bot.runtime_state))
    r2 = StraddleRunner(eng2)
    r2.positions = dict(r.positions)
    assert r2.state.working == "LONG" and r2.state.adds == 1
    await tick(r2, 104)
    eng2._executor.add_to_position.assert_awaited_once()


def test_schema_straddle_requires_neutral():
    cfg = StrategyConfig(**CFG)
    assert BotCreate(name="s", symbol="SOLUSDT", side="NEUTRAL", config=cfg).side == "NEUTRAL"
    with pytest.raises(ValueError):
        BotCreate(name="s", symbol="SOLUSDT", side="LONG", config=cfg)
    with pytest.raises(ValueError):
        BotCreate(name="p", symbol="SOLUSDT", side="NEUTRAL", config=StrategyConfig())
