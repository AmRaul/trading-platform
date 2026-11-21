"""PriceTracker, HTTP API подписок и BybitPriceStream без сети и без Redis."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import app.adapters.bybit_stream as bs
from app import api
from app.tracker import PriceTracker


class FakePipe:
    def __init__(self, redis):
        self.redis, self.ops = redis, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def set(self, key, value, ex=None):
        self.ops.append(("set", key, value, ex))

    def publish(self, channel, payload):
        self.ops.append(("publish", channel, payload))

    async def execute(self):
        self.redis.executed.extend(self.ops)


class FakeRedis:
    def __init__(self):
        self.executed = []

    def pipeline(self):
        return FakePipe(self)


class FakeStream:
    def __init__(self):
        self.subs, self.unsubs, self.closed = [], [], False

    async def subscribe(self, symbol, cb):
        self.subs.append(symbol)
        self.cb = cb

    async def unsubscribe(self, symbol):
        self.unsubs.append(symbol)

    async def close(self):
        self.closed = True


def make_tracker():
    redis, stream = FakeRedis(), FakeStream()
    t = PriceTracker(redis)
    t.register_exchange("bybit", stream)
    return t, redis, stream


@pytest.mark.asyncio
async def test_price_goes_to_key_and_channel():
    t, redis, stream = make_tracker()
    await t.subscribe("bybit", "SOLUSDT")
    await stream.cb("bybit", "SOLUSDT", 142.5)
    (_, key, value, ex), (_, channel, payload) = redis.executed
    assert (key, value, ex) == ("price:SOLUSDT", "142.5", 60)  # ключ протухает, если поток встал
    assert channel == "prices:bybit:SOLUSDT"
    assert json.loads(payload) == {"exchange": "bybit", "symbol": "SOLUSDT", "price": 142.5}


@pytest.mark.asyncio
async def test_subscribe_is_idempotent_and_unknown_exchange_fails():
    t, _, stream = make_tracker()
    await t.subscribe("bybit", "SOLUSDT")
    await t.subscribe("bybit", "SOLUSDT")
    assert stream.subs == ["SOLUSDT"]
    with pytest.raises(ValueError):
        await t.subscribe("binance", "SOLUSDT")


@pytest.mark.asyncio
async def test_unsubscribe_then_subscribe_again():
    t, _, stream = make_tracker()
    await t.subscribe("bybit", "LINKUSDT")
    await t.unsubscribe("bybit", "LINKUSDT")
    await t.subscribe("bybit", "LINKUSDT")
    assert stream.subs == ["LINKUSDT", "LINKUSDT"] and stream.unsubs == ["LINKUSDT"]


def test_http_api_subscriptions():
    t, _, _ = make_tracker()
    api.set_tracker(t)
    c = TestClient(api.app)
    assert c.post("/subscribe", json={"exchange": "bybit", "symbol": "AVAXUSDT"}).json()["status"] == "ok"
    assert c.get("/subscriptions").json() == {"bybit": ["AVAXUSDT"]}
    assert c.post("/subscribe", json={"exchange": "nope", "symbol": "X"}).status_code == 400
    assert c.request("DELETE", "/subscribe", json={"exchange": "bybit", "symbol": "AVAXUSDT"}).status_code == 200
    assert c.get("/subscriptions").json() == {"bybit": []}
    assert c.get("/health").json() == {"status": "healthy"}


# ---------- BybitPriceStream ----------

class FakeWS:
    instances = []

    def __init__(self, testnet, channel_type):
        self.topics, self.exited = {}, False
        self.fail_already = set()
        FakeWS.instances.append(self)

    def ticker_stream(self, symbol, callback):
        if symbol in self.fail_already:
            raise Exception(f"Cannot subscribe to tickers.{symbol} - already subscribed")
        self.topics[symbol] = callback

    def exit(self):
        self.exited = True


@pytest.fixture
def fake_ws(monkeypatch):
    FakeWS.instances = []
    monkeypatch.setattr(bs, "WebSocket", FakeWS)
    return FakeWS


async def collect(stream, symbol, got):
    async def cb(ex, sym, price):
        got.append((ex, sym, price))
    await stream.subscribe(symbol, cb)


@pytest.mark.asyncio
async def test_bybit_ticks_reach_callback(fake_ws):
    s, got = bs.BybitPriceStream(), []
    await collect(s, "SOLUSDT", got)
    on_msg = fake_ws.instances[0].topics["SOLUSDT"]
    for m in ({"data": {"lastPrice": "150.1"}}, {"data": {}}, {"data": {"lastPrice": "0"}},
              {"data": {"lastPrice": "abc"}}, {"data": {"lastPrice": "151"}}):
        on_msg(m)  # колбэк pybit приходит из чужого потока
    await asyncio.sleep(0.05)
    assert got == [("bybit", "SOLUSDT", 150.1), ("bybit", "SOLUSDT", 151.0)]  # мусор отброшен, поток жив
    await s.close()


@pytest.mark.asyncio
async def test_already_subscribed_rebuilds_socket_for_all_symbols(fake_ws):
    s, got = bs.BybitPriceStream(), []
    await collect(s, "SOLUSDT", got)
    await collect(s, "LINKUSDT", got)
    first = fake_ws.instances[0]
    # после тихого реконнекта pybit отвечает «already subscribed», хотя тиков нет
    await s.unsubscribe("AVAXUSDT")
    first.fail_already.add("AVAXUSDT")
    await collect(s, "AVAXUSDT", got)
    assert first.exited and len(fake_ws.instances) == 2
    assert set(fake_ws.instances[1].topics) == {"SOLUSDT", "LINKUSDT", "AVAXUSDT"}
    await s.close()


@pytest.mark.asyncio
async def test_watchdog_reconnects_silent_socket(fake_ws, monkeypatch):
    monkeypatch.setattr(bs.BybitPriceStream, "WATCHDOG_INTERVAL", 0.01)
    monkeypatch.setattr(bs.BybitPriceStream, "STALE_AFTER", 0.02)
    s, got = bs.BybitPriceStream(), []
    await collect(s, "SOLUSDT", got)
    await asyncio.sleep(0.1)
    assert len(fake_ws.instances) >= 2 and fake_ws.instances[0].exited
    assert "SOLUSDT" in fake_ws.instances[-1].topics
    await s.close()


@pytest.mark.asyncio
async def test_watchdog_quiet_while_messages_flow(fake_ws, monkeypatch):
    monkeypatch.setattr(bs.BybitPriceStream, "WATCHDOG_INTERVAL", 0.01)
    monkeypatch.setattr(bs.BybitPriceStream, "STALE_AFTER", 0.05)
    s, got = bs.BybitPriceStream(), []
    await collect(s, "SOLUSDT", got)
    for _ in range(10):
        fake_ws.instances[0].topics["SOLUSDT"]({"data": {"lastPrice": "1"}})
        await asyncio.sleep(0.01)
    assert len(fake_ws.instances) == 1
    await s.close()
