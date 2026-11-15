from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.routes.ready_strategies import launch_ready_strategy
from app.schemas.ready_strategy import LaunchRequest

SLUG = "mrc-dca-btc-15m-long"


def _db(account_exists=True):
    db = AsyncMock()
    db.add = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = MagicMock() if account_exists else None
    db.execute = AsyncMock(return_value=result)
    return db


def _user():
    u = MagicMock()
    u.id = 7
    return u


async def _launch(db=None, **kw):
    req = LaunchRequest(**{"variant_key": "conservative", "deposit_usdt": 5700,
                           "exchange": "bybit", "bybit_account_id": 3, **kw})
    db = db or _db()
    await launch_ready_strategy(SLUG, req, db, _user())
    return db.add.call_args.args[0]


@pytest.mark.asyncio
async def test_launch_conservative_creates_bot_waiting_for_signal():
    bot = await _launch()
    assert bot.state == "SIGNAL"
    assert bot.user_id == 7
    assert bot.symbol == "BTCUSDT" and bot.side == "LONG"
    assert bot.exchange == "bybit" and bot.bybit_account_id == 3 and bot.account_id is None
    assert bot.config["entry_size_usdt"] == pytest.approx(279.3)  # 5700 × 4.9%
    assert bot.config["bot_type"] == "dca"
    assert bot.config["order_count"] == 5
    assert bot.config["sl_initial"] == 20.0
    assert bot.config["entry_signal"]["trend_ema_period"] == 200
    assert bot.config["cycle"] is True
    assert "Консервативный" in bot.name


@pytest.mark.asyncio
async def test_launch_aggressive_doubles_first_order():
    bot = await _launch(variant_key="aggressive")
    assert bot.config["entry_size_usdt"] == pytest.approx(558.6)  # 5700 × 9.8%


@pytest.mark.asyncio
async def test_launch_on_cryptorg_uses_cryptorg_account():
    bot = await _launch(exchange="cryptorg", account_id=4, bybit_account_id=None)
    assert bot.exchange == "cryptorg" and bot.account_id == 4 and bot.bybit_account_id is None


@pytest.mark.asyncio
async def test_launch_rejects_too_small_deposit():
    with pytest.raises(HTTPException) as e:
        await _launch(deposit_usdt=100)  # первый ордер 4.9 USDT < 10
    assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_launch_unknown_variant():
    with pytest.raises(HTTPException) as e:
        await _launch(variant_key="yolo")
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_launch_unknown_strategy():
    req = LaunchRequest(variant_key="conservative", deposit_usdt=5700, bybit_account_id=3)
    with pytest.raises(HTTPException) as e:
        await launch_ready_strategy("nope", req, _db(), _user())
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_launch_requires_account():
    with pytest.raises(HTTPException) as e:
        await _launch(bybit_account_id=None)
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        await _launch(exchange="cryptorg", account_id=None, bybit_account_id=None)
    assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_launch_rejects_foreign_account():
    with pytest.raises(HTTPException) as e:
        await _launch(db=_db(account_exists=False))
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_launch_multi_coin_creates_bot_per_coin():
    req = LaunchRequest(variant_key="conservative", deposit_usdt=5000, exchange="bybit", bybit_account_id=3)
    db = _db()
    bots = await launch_ready_strategy("alt-short-pyramid-5", req, db, _user())
    assert [b.symbol for b in bots] == ["SOLUSDT", "AVAXUSDT", "LINKUSDT", "ETHUSDT", "XRPUSDT"]
    assert db.add.call_count == 5
    by_symbol = {b.symbol: b for b in bots}
    assert by_symbol["SOLUSDT"].config["trailing_percent"] == 8.1
    assert by_symbol["ETHUSDT"].config["trailing_percent"] == 5.0
    for b in bots:
        assert b.side == "SHORT" and b.state == "SIGNAL"
        assert b.config["entry_size_usdt"] == pytest.approx(250)  # 5000 × 5%
        assert b.config["bot_type"] == "pyramiding" and b.config["order_count"] == 4
        assert b.config["entry_signal"]["type"] == "supertrend"
        assert b.config["entry_signal"]["trend_ema_fast"] == 50
        assert b.symbol in b.name


@pytest.mark.asyncio
async def test_launch_multi_coin_aggressive():
    req = LaunchRequest(variant_key="aggressive", deposit_usdt=5000, exchange="bybit", bybit_account_id=3)
    bots = await launch_ready_strategy("alt-short-pyramid-5", req, _db(), _user())
    assert all(b.config["entry_size_usdt"] == pytest.approx(500) for b in bots)


def test_catalog_backtests_load():
    from app.domain.ready_strategies.catalog import list_strategies
    from app.schemas.ready_strategy import ReadyStrategyBacktest
    for s in list_strategies():
        for v in s.variants:
            ReadyStrategyBacktest(**v.backtest())
