"""Cryptorg: команды — webhook, подтверждение — позиция на Bybit (ключ счёта «Bybit-ликвидность»)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.adapters.cryptorg_executor import CryptorgExecutorAdapter
from app.ports.exchange_executor import ExchangeExecutor


class Reader:
    """Позиция на бирже по шагам: каждый get_position отдаёт следующее состояние, последнее повторяется."""

    def __init__(self, *states):
        self.states = list(states)
        self.calls = 0

    async def get_position(self, symbol, side):
        self.calls += 1
        state = self.states[0] if len(self.states) == 1 else self.states.pop(0)
        if isinstance(state, Exception):
            raise state
        return state


def _client(ok=True):
    c = MagicMock()
    for name in ("open_position", "add_to_position", "close_position", "update_stop_and_tp"):
        setattr(c, name, AsyncMock(return_value={"success": ok, **({} if ok else {"error": "webhook"})}))
    return c


def _ex(client, reader=None):
    return CryptorgExecutorAdapter(client, reader=reader, sleep=AsyncMock(), confirm_timeout=0.05, poll=0.01)


OPEN = dict(symbol="SOLUSDT", side="short", order_volume_usdt=250, leverage=10, sl_percent=2, tp_percent=6)


def test_satisfies_port():
    assert isinstance(_ex(_client()), ExchangeExecutor)


@pytest.mark.asyncio
async def test_without_key_works_blind_like_before():
    client = _client()
    ex = _ex(client)
    assert ex.can_verify is False
    assert (await ex.open_position(**OPEN))["success"] is True
    assert await ex.get_open_position_size("SOLUSDT", "short") is None
    client.open_position.assert_awaited_once()


@pytest.mark.asyncio
async def test_open_confirmed_returns_real_avg_price():
    ex = _ex(_client(), Reader((0.0, 0.0), (0.0, 0.0), (3.4, 73.5)))
    res = await ex.open_position(**OPEN)
    assert res["success"] is True and res["avg_price"] == 73.5 and res["exchange_size"] == 3.4


@pytest.mark.asyncio
async def test_open_refused_when_position_already_on_exchange():
    """Ghost Bot сопоставляет сделку по монете и стороне — новый вход усреднил бы чужую позицию."""
    client = _client()
    res = await _ex(client, Reader((2.0, 70.0))).open_position(**OPEN)
    assert res["success"] is False and "уже открыта" in res["error"]
    client.open_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_open_refused_when_exchange_unreadable():
    client = _client()
    res = await _ex(client, Reader(None)).open_position(**OPEN)
    assert res["success"] is False
    client.open_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_open_webhook_error_but_position_appeared_is_success():
    """Таймаут webhook при исполненной сделке: без этого бот открыл бы вторую."""
    res = await _ex(_client(ok=False), Reader((0.0, 0.0), (3.4, 73.5))).open_position(**OPEN)
    assert res["success"] is True and res["avg_price"] == 73.5


@pytest.mark.asyncio
async def test_open_accepted_but_never_filled_is_failure():
    res = await _ex(_client(), Reader((0.0, 0.0))).open_position(**OPEN)
    assert res["success"] is False and "не появилась" in res["error"] and "принят" in res["error"]


@pytest.mark.asyncio
async def test_add_fill_price_from_position_value_growth():
    # было 10 @ 100, стало 20 @ 99 → добрано 10 по (20*99 - 10*100) / 10 = 98
    ex = _ex(_client(), Reader((10.0, 100.0), (10.0, 100.0), (20.0, 99.0)))
    res = await ex.add_to_position("SOLUSDT", "long", 1000)
    assert res["success"] is True
    assert res["fill_price"] == pytest.approx(98.0) and res["avg_price"] == 99.0


@pytest.mark.asyncio
async def test_add_not_filled_is_failure():
    res = await _ex(_client(), Reader((10.0, 100.0))).add_to_position("SOLUSDT", "long", 1000)
    assert res["success"] is False and "не исполнился" in res["error"]


@pytest.mark.asyncio
async def test_add_refused_without_position_on_exchange():
    client = _client()
    res = await _ex(client, Reader((0.0, 0.0))).add_to_position("SOLUSDT", "long", 1000)
    assert res["success"] is False
    client.add_to_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_confirmed_only_when_position_gone():
    assert (await _ex(_client(), Reader((5.0, 70.0), (0.0, 0.0))).close_position("SOLUSDT", "short"))["success"]
    res = await _ex(_client(), Reader((5.0, 70.0))).close_position("SOLUSDT", "short")
    assert res["success"] is False and "осталось 5" in res["error"]


@pytest.mark.asyncio
async def test_close_webhook_error_but_closed_is_success():
    """Биржа сама закрыла по стопу Cryptorg, webhook «нечего закрывать» — цель достигнута."""
    assert (await _ex(_client(ok=False), Reader((0.0, 0.0))).close_position("SOLUSDT", "short"))["success"]


@pytest.mark.asyncio
async def test_reader_exception_is_unknown_not_closed():
    ex = _ex(_client(), Reader(RuntimeError("timeout")))
    assert await ex.get_open_position_size("SOLUSDT", "short") is None
    assert (await ex.close_position("SOLUSDT", "short"))["success"] is False


@pytest.mark.asyncio
async def test_stop_percent_sent_unsigned():
    client = _client()
    await _ex(client).update_stop_and_tp("SOLUSDT", "long", -2.0, None)
    assert client.update_stop_and_tp.await_args.kwargs["sl_percent"] == 2.0
