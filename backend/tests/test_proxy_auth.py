"""nginx auth_request для signals./backtester.: кто что может."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import auth
from app.core.config import settings

ADMIN = SimpleNamespace(username="boss")
USER = SimpleNamespace(username="beta")


@pytest.fixture(autouse=True)
def admin_name(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "boss")


@pytest.mark.parametrize("method,uri", [
    ("GET", "/api/backtest-history?limit=1"),
    ("GET", "/api/signal-strategies/"),
    ("OPTIONS", "/api/backtest/clear-all"),
    ("POST", "/api/run-backtest"),
    ("POST", "/api/optimize/start"),
])
def test_user_allowed(method, uri):
    assert auth.proxy_access_allowed(USER, method, uri)


@pytest.mark.parametrize("method,uri", [
    ("DELETE", "/api/backtest/clear-all"),
    ("DELETE", "/api/backtest/abc"),
    ("POST", "/api/configs"),
    ("POST", "/api/signal-strategies/"),
    ("PATCH", "/api/signal-strategies/3"),
    ("DELETE", "/api/trend-symbols/1"),
    ("POST", "/api/screener/scan"),
    ("POST", "/api/run-backtest-evil"),  # префикс без «/» не считается
])
def test_user_denied_admin_allowed(method, uri):
    assert not auth.proxy_access_allowed(USER, method, uri)
    assert auth.proxy_access_allowed(ADMIN, method, uri)


def test_empty_admin_username_denies_writes(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "")
    assert not auth.proxy_access_allowed(SimpleNamespace(username=""), "DELETE", "/api/backtest/clear-all")


def _req(method, uri):
    return SimpleNamespace(headers={"X-Original-Method": method, "X-Original-URI": uri})


@pytest.mark.asyncio
async def test_verify_endpoint():
    assert (await auth.verify_for_proxy(_req("GET", "/api/x"), USER)).status_code == 204
    with pytest.raises(HTTPException) as e:
        await auth.verify_for_proxy(_req("DELETE", "/api/backtest/clear-all"), USER)
    assert e.value.status_code == 403
    assert (await auth.verify_for_proxy(_req("DELETE", "/api/backtest/clear-all"), ADMIN)).status_code == 204
