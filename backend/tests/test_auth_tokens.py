"""Короткий access + refresh в httpOnly-cookie; авторизованный WebSocket с событиями только владельцу."""
import asyncio
import importlib.util
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Response
from jose import jwt
from starlette.requests import Request

from app.api import deps
from app.api.routes import auth
from app.core import security
from app.core.config import settings

USER = SimpleNamespace(id=7, username="raul", hashed_password="$2b$12$hash-one")


class FakeResult:
    def __init__(self, obj):
        self.obj = obj

    def scalar_one_or_none(self):
        return self.obj


class FakeDB:
    def __init__(self, user):
        self.user = user

    async def execute(self, _):
        return FakeResult(self.user)


def request(cookie=None, scheme="https"):
    headers = [(b"cookie", f"{auth.REFRESH_COOKIE}={cookie}".encode())] if cookie else []
    return Request({"type": "http", "method": "POST", "path": "/api/auth/refresh", "headers": headers,
                    "scheme": scheme, "server": ("kandle", 443), "query_string": b""})


def cookie_from(resp: Response) -> str:
    raw = resp.headers["set-cookie"]
    return raw.split(";", 1)[0].split("=", 1)[1]


# ---------- токены ----------

def test_access_token_is_short_and_typed():
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES <= 60
    p = security.decode_token(security.create_access_token({"sub": "raul"}), "access")
    assert p["sub"] == "raul" and p["type"] == "access"


def test_refresh_token_not_accepted_as_bearer():
    rt = security.create_refresh_token("raul", USER.hashed_password)
    assert security.decode_access_token(rt) is None
    assert security.decode_token(security.create_access_token({"sub": "raul"}), "refresh") is None


def test_legacy_token_without_type_still_works_as_access():
    legacy = jwt.encode({"sub": "raul", "exp": 4102444800}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    assert security.decode_access_token(legacy)["sub"] == "raul"


def test_expired_and_forged_rejected():
    expired = security.create_access_token({"sub": "raul"}, expires_delta=timedelta(seconds=-1))
    forged = jwt.encode({"sub": "raul", "type": "access", "exp": 4102444800}, "other-key", algorithm="HS256")
    assert security.decode_access_token(expired) is None and security.decode_access_token(forged) is None


# ---------- вход / обновление / выход ----------

def test_session_sets_httponly_strict_cookie():
    resp = Response()
    body = auth._session_response(resp, request(), USER)
    raw = resp.headers["set-cookie"].lower()
    assert body["access_token"] and "httponly" in raw and "samesite=strict" in raw
    assert "path=/api/auth" in raw and "secure" in raw and f"max-age={30 * 86400}" in raw


def test_cookie_not_secure_on_plain_http_localhost():
    resp = Response()
    auth._session_response(resp, request(scheme="http"), USER)
    assert "secure" not in resp.headers["set-cookie"].lower()


@pytest.mark.asyncio
async def test_refresh_gives_new_access_and_rotates_cookie():
    resp = Response()
    rt = security.create_refresh_token(USER.username, USER.hashed_password)
    body = await auth.refresh(request(rt), resp, FakeDB(USER))
    assert security.decode_access_token(body["access_token"])["sub"] == "raul"
    assert security.decode_token(cookie_from(resp), "refresh")["sub"] == "raul"


@pytest.mark.asyncio
@pytest.mark.parametrize("cookie", [None, "garbage", "access"])
async def test_refresh_without_valid_cookie_is_401_and_clears(cookie):
    if cookie == "access":
        cookie = security.create_access_token({"sub": "raul"})
    out = await auth.refresh(request(cookie), Response(), FakeDB(USER))
    assert out.status_code == 401 and 'kandle_refresh=""' in out.headers["set-cookie"]


@pytest.mark.asyncio
async def test_password_change_revokes_refresh():
    rt = security.create_refresh_token(USER.username, USER.hashed_password)
    changed = SimpleNamespace(**{**USER.__dict__, "hashed_password": "$2b$12$hash-two"})
    out = await auth.refresh(request(rt), Response(), FakeDB(changed))
    assert out.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_cookie():
    out = await auth.logout()
    assert out.status_code == 204 and "max-age=0" in out.headers["set-cookie"].lower()


@pytest.mark.asyncio
async def test_user_from_access_token():
    good = security.create_access_token({"sub": "raul"})
    assert await deps.user_from_access_token(good, FakeDB(USER)) is USER
    assert await deps.user_from_access_token(None, FakeDB(USER)) is None
    assert await deps.user_from_access_token(security.create_refresh_token("raul", "h"), FakeDB(USER)) is None


# ---------- WebSocket ----------

# conftest подменяет app.services.websocket моком — грузим настоящие модули из файлов
def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent.parent / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ws_service = _load("real_ws_service_auth", "app/services/websocket.py")


class FakeWS:
    def __init__(self, first=None, hang=False):
        self.first, self.hang, self.sent, self.closed = first, hang, [], None

    async def receive_json(self):
        if self.hang:
            await asyncio.sleep(10)
        return self.first

    async def send_json(self, msg):
        self.sent.append(msg)


@pytest.mark.asyncio
async def test_events_go_only_to_bot_owner():
    m = ws_service.ConnectionManager()
    m.bot_owner = {1: 7, 2: 8}
    mine, other = FakeWS(), FakeWS()
    await m.connect(mine, 7)
    await m.connect(other, 8)
    await m.broadcast_event("position_closed", {"bot_id": 1, "pnl": 3.2})
    await m.broadcast_event("trailing_stop_moved", {"bot_id": 2})
    assert [x["type"] for x in mine.sent] == ["position_closed"]
    assert [x["type"] for x in other.sent] == ["trailing_stop_moved"]


@pytest.mark.asyncio
async def test_event_without_bot_goes_nowhere():
    m = ws_service.ConnectionManager()
    ws = FakeWS()
    await m.connect(ws, 7)
    await m.broadcast_event("something", {"x": 1})
    assert ws.sent == [] and await m.owner_of("not-a-number") is None


@pytest.mark.asyncio
async def test_ws_authenticate(monkeypatch):
    import app.api.routes.websocket as route

    class Sess:
        async def __aenter__(self):
            return FakeDB(USER)

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(route, "AsyncSessionLocal", lambda: Sess())
    monkeypatch.setattr(route, "AUTH_TIMEOUT_SEC", 0.05)
    token = security.create_access_token({"sub": "raul"})
    assert await route.authenticate(FakeWS({"type": "auth", "token": token})) is USER
    assert await route.authenticate(FakeWS({"type": "subscribe_price", "symbol": "SOLUSDT"})) is None
    assert await route.authenticate(FakeWS({"type": "auth", "token": "bad"})) is None
    assert await route.authenticate(FakeWS(hang=True)) is None  # молчит — отключаем
