import asyncio
import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# conftest подменяет app.services.websocket моком — грузим настоящий модуль из файла
_spec = importlib.util.spec_from_file_location(
    "real_websocket", Path(__file__).parent.parent / "app" / "services" / "websocket.py")
ws = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ws)


class FakePubSub:
    """Первый экземпляр падает как при остановке Redis, второй отдаёт одну цену."""

    def __init__(self, fail: bool):
        self.fail = fail
        self.subscribed = []
        self.closed = False

    async def subscribe(self, *channels):
        self.subscribed.extend(channels)

    async def listen(self):
        if self.fail:
            raise ConnectionError("Error -2 connecting to redis:6379")
        yield {"type": "subscribe", "data": 1}
        yield {"type": "message", "data": json.dumps({"exchange": "bybit", "symbol": "SOLUSDT", "price": "150.5"})}
        await asyncio.Event().wait()  # дальше тишина, как у живого канала

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_listener_reconnects_and_resubscribes(monkeypatch):
    pubsubs = [FakePubSub(fail=True), FakePubSub(fail=False)]
    redis = MagicMock()
    redis.pubsub = MagicMock(side_effect=pubsubs)
    monkeypatch.setattr(ws, "get_redis", AsyncMock(return_value=redis))
    monkeypatch.setattr(ws, "RECONNECT_MIN_DELAY", 0)
    monkeypatch.setattr(ws.manager, "broadcast_price_update", AsyncMock())

    psm = ws.PriceStreamManager()
    psm._listened_channels.add("prices:bybit:SOLUSDT")
    psm._update_strategies = AsyncMock()

    task = asyncio.create_task(psm._listen_loop())
    for _ in range(100):
        if psm._update_strategies.await_count:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert pubsubs[0].closed
    assert pubsubs[1].subscribed == ["prices:bybit:SOLUSDT"]
    psm._update_strategies.assert_awaited_once_with("SOLUSDT", 150.5)
    assert pubsubs[1].closed


@pytest.mark.asyncio
async def test_listener_exits_without_channels():
    psm = ws.PriceStreamManager()
    await asyncio.wait_for(psm._listen_loop(), timeout=1)
