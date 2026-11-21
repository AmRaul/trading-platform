"""Доступ (одобрение, блокировка), попытки входа, смена пароля, лимит ботов, личные алерты."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api import deps
from app.application.monitoring.alert_state import AlertState, bot_problems
from app.core import login_limiter


def _u(username="anna", **kw):
    return SimpleNamespace(**{"id": 2, "username": username, "is_active": True, "approved": True, **kw})


def test_access_rules(monkeypatch):
    monkeypatch.setattr(deps.settings, "ADMIN_USERNAME", "raul")
    assert deps.access_denied_reason(_u()) is None
    assert "ждёт одобрения" in deps.access_denied_reason(_u(approved=False))
    assert "закрыт" in deps.access_denied_reason(_u(is_active=False))
    # владельца платформы не запереть даже ошибкой в базе
    assert deps.access_denied_reason(_u("raul", approved=False, is_active=False)) is None


def test_login_limiter_blocks_after_ten_failures_per_ip_and_login():
    login_limiter.reset()
    for i in range(login_limiter.MAX_FAILURES):
        assert login_limiter.retry_after("1.1.1.1", "anna", now=1000 + i) is None
        login_limiter.failed("1.1.1.1", "anna", now=1000 + i)
    assert login_limiter.retry_after("1.1.1.1", "ANNA", now=1010) > 0  # регистр логина не помогает
    assert login_limiter.retry_after("2.2.2.2", "anna", now=1010) is None  # другой IP
    assert login_limiter.retry_after("1.1.1.1", "anna", now=1000 + login_limiter.WINDOW_SEC + 20) is None
    login_limiter.reset()


def test_password_change_requires_strong_password():
    from app.schemas.auth import PasswordChange
    assert PasswordChange(old_password="x", new_password="Str0ng#Pass").new_password == "Str0ng#Pass"
    with pytest.raises(ValueError):
        PasswordChange(old_password="x", new_password="weakweak")


@pytest.mark.asyncio
async def test_bot_limit(monkeypatch):
    from app.api.routes import me
    monkeypatch.setattr(me.settings, "MAX_BOTS_PER_USER", 20)
    monkeypatch.setattr(deps.settings, "ADMIN_USERNAME", "raul")
    result = MagicMock()
    result.scalar.return_value = 18
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    await me.ensure_bot_capacity(db, _u(), adding=2)  # 18 + 2 = 20 — можно
    with pytest.raises(HTTPException) as e:
        await me.ensure_bot_capacity(db, _u(), adding=5)  # готовая стратегия на 5 монет не влезает
    assert e.value.status_code == 403 and "Лимит ботов: 20" in e.value.detail
    await me.ensure_bot_capacity(db, _u("raul"), adding=100)  # владелец без лимита


def test_alert_state_new_gone_remind():
    report = {"bots": [{"bot_id": 1, "name": "Шорт SOL", "symbol": "SOLUSDT", "status": "problem",
                        "issues": ["последний тик цены 7 мин назад"]},
                       {"bot_id": 2, "name": "ok", "symbol": "ETHUSDT", "status": "ok", "issues": []}]}
    st = AlertState(remind_sec=3600)
    msgs = st.update(bot_problems(report), now=0)
    assert len(msgs) == 1 and msgs[0].startswith("🔴") and "Шорт SOL" in msgs[0]
    report["bots"][0]["issues"] = ["последний тик цены 12 мин назад"]  # то же самое, другие числа
    assert st.update(bot_problems(report), now=600) == []
    assert st.update(bot_problems(report), now=4000)[0].startswith("⏰")
    assert st.update({}, now=4100)[0].startswith("✅")
