"""Торговые роуты работают только с ботами текущего пользователя."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import app.api.routes.trading as trading

ROUTES = [
    (trading.manual_entry, trading.ManualEntryRequest(bot_id=5, account_balance=0)),
    (trading.limit_entry, trading.LimitEntryRequest(bot_id=5, limit_price=1.0)),
    (trading.signal_entry, trading.SignalEntryRequest(bot_id=5)),
    (trading.cancel_limit_entry, trading.CancelLimitRequest(bot_id=5)),
    (trading.manual_close, trading.ManualCloseRequest(bot_id=5)),
]


def _db(owned: bool):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = 5 if owned else None
    db.execute = AsyncMock(return_value=result)
    return db


def _user():
    u = MagicMock()
    u.id = 1
    return u


@pytest.fixture
def engine_cls(monkeypatch):
    engine = MagicMock()
    engine.initialize = AsyncMock()
    ok = AsyncMock(return_value={"success": True})
    for name in ("manual_entry", "set_limit_entry", "arm_signal_entry", "cancel_limit_entry", "manual_close"):
        setattr(engine, name, ok)
    cls = MagicMock(return_value=engine)
    monkeypatch.setattr(trading, "StrategyEngine", cls)
    return cls


@pytest.mark.asyncio
@pytest.mark.parametrize("route,request_body", ROUTES)
async def test_foreign_bot_is_404_and_untouched(route, request_body, engine_cls):
    with pytest.raises(HTTPException) as e:
        await route(request_body, _db(owned=False), _user())
    assert e.value.status_code == 404
    engine_cls.assert_not_called()  # движок чужого бота даже не создаётся


@pytest.mark.asyncio
@pytest.mark.parametrize("route,request_body", ROUTES)
async def test_own_bot_works(route, request_body, engine_cls):
    result = await route(request_body, _db(owned=True), _user())
    assert result == {"success": True}
    engine_cls.assert_called_once()
