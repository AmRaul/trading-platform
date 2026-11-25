"""Витрина готовых стратегий открыта без входа; запуск — только с пользователем."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.ready_strategies import router
from app.core.database import get_db


async def _no_db():
    yield None


def _client():
    app = FastAPI()
    app.include_router(router, prefix="/api/ready-strategies")
    app.dependency_overrides[get_db] = _no_db
    return TestClient(app)


def test_list_and_detail_open_without_token():
    c = _client()
    r = c.get("/api/ready-strategies/")
    assert r.status_code == 200 and any(s["slug"] == "donchian-long-6" for s in r.json())
    d = c.get("/api/ready-strategies/donchian-long-6")
    assert d.status_code == 200 and d.json()["variants"][0]["backtest"]["metrics"]


def test_launch_still_requires_login():
    r = _client().post("/api/ready-strategies/donchian-long-6/launch",
                       json={"variant_key": "base", "deposit_usdt": 6000, "exchange": "paper"})
    assert r.status_code == 401, r.text
