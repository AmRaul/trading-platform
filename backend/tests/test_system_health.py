"""Честный /health и 401 без токена."""
import asyncio
import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.deps import get_current_user
from app.application.monitoring import system_health as sh

# conftest подменяет app.services.websocket моком — грузим настоящий модуль из файла
_spec = importlib.util.spec_from_file_location(
    "real_websocket_health", Path(__file__).parent.parent / "app" / "services" / "websocket.py")
_ws = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ws)
PriceStreamManager = _ws.PriceStreamManager


async def ok():
    return 1


async def boom():
    raise ConnectionError("down")


async def hang():
    await asyncio.sleep(10)


@pytest.mark.asyncio
async def test_all_ok():
    healthy, checks = await sh.system_health(db_check=ok, redis_check=ok, scheduler_running=True,
                                             price_listener_alive=True)
    assert healthy and all(checks.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("kw,failed", [
    (dict(db_check=boom), "db"),
    (dict(redis_check=boom), "redis"),
    (dict(scheduler_running=False), "scheduler"),
    (dict(price_listener_alive=False), "prices"),
])
async def test_any_failure_is_unhealthy(kw, failed):
    base = dict(db_check=ok, redis_check=ok, scheduler_running=True, price_listener_alive=True)
    healthy, checks = await sh.system_health(**{**base, **kw})
    assert not healthy and checks[failed] is False
    assert sum(not v for v in checks.values()) == 1


@pytest.mark.asyncio
async def test_hanging_db_times_out(monkeypatch):
    monkeypatch.setattr(sh, "CHECK_TIMEOUT_SEC", 0.05)
    healthy, checks = await sh.system_health(db_check=hang, redis_check=ok, scheduler_running=True,
                                             price_listener_alive=True)
    assert not healthy and checks["db"] is False


@pytest.mark.asyncio
async def test_price_listener_alive_rules():
    m = PriceStreamManager()
    assert m.listener_alive  # нет каналов — слушатель и не нужен
    m._listened_channels.add("prices:bybit:SOLUSDT")
    assert not m.listener_alive  # есть каналы, задачи нет
    m._pubsub_task = asyncio.create_task(asyncio.sleep(10))
    assert m.listener_alive
    m._pubsub_task.cancel()


@pytest.mark.asyncio
async def test_missing_token_is_401():
    with pytest.raises(HTTPException) as e:
        await get_current_user(credentials=None, db=None)
    assert e.value.status_code == 401
