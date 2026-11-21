"""
Интеграция на настоящем Postgres: регистрация с одобрением, вход, блокировка, смена пароля,
привязка Telegram кодом (/start), лимит ботов, личный алерт пользователю.
Telegram API подменён — проверяем, что и кому мы бы отправили.

Запуск (CI — job «Integration · backend»): alembic upgrade head && python integration/users_telegram.py
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import HTTPException


def ok(cond, msg):
    print(("OK  " if cond else "FAIL") + " " + msg)
    if not cond:
        raise SystemExit(1)


class Req:
    """Минимальный Request для роутов авторизации."""
    def __init__(self, cookies=None):
        self.headers = {"X-Real-IP": "10.0.0.1"}
        self.client = SimpleNamespace(host="10.0.0.1")
        self.url = SimpleNamespace(scheme="http")
        self.cookies = cookies or {}


async def main():
    from fastapi import Response
    from sqlalchemy import select

    from app.api import deps
    from app.api.routes import admin, auth, me
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.core.redis import close_redis, init_redis
    from app.models import Bot, User
    from app.schemas.auth import PasswordChange, UserCreate, UserLogin
    from app.services import telegram_notifier as tn
    from app.services import user_alerts as ua
    from app.services.telegram_bot import TelegramBot

    settings.ADMIN_USERNAME = "owner"
    settings.TELEGRAM_BOT_TOKEN = "test-token"
    settings.MAX_BOTS_PER_USER = 3
    sent = []

    async def fake_call(token, method, payload, timeout=10):
        sent.append((method, payload))
        return {"message_id": 1}

    tn.telegram_call = fake_call
    tn.notifier.token, tn.notifier.owner, tn.notifier.owner_chat_id = "test-token", "owner", "owner-chat"
    await init_redis()

    async with AsyncSessionLocal() as db:
        r = await auth.register(UserCreate(username="owner", password="Own3r#Pass"), Req(), Response(), db)
        ok(isinstance(r, dict) and r.get("access_token"), "владелец платформы входит сразу после регистрации")
        owner = (await db.execute(select(User).where(User.username == "owner"))).scalar_one()

        r = await auth.register(UserCreate(username="anna", password="Ann4#Strong"), Req(), Response(), db)
        ok(r.status_code == 202, "новый пользователь — заявка (202), без токена")
        await asyncio.sleep(0.05)
        ok(any("Новая заявка" in p.get("text", "") and p["chat_id"] == "owner-chat" for _, p in sent),
           "владельцу ушло сообщение о заявке")
        anna = (await db.execute(select(User).where(User.username == "anna"))).scalar_one()

        try:
            await auth.login(UserLogin(username="anna", password="Ann4#Strong"), Req(), Response(), db)
            ok(False, "вход до одобрения должен быть закрыт")
        except HTTPException as e:
            ok(e.status_code == 403 and "одобрения" in e.detail, "до одобрения вход закрыт (403)")

        await admin.approve_user(anna.id, db=db, admin=owner)
        tok = await auth.login(UserLogin(username="anna", password="Ann4#Strong"), Req(), Response(), db)
        ok(bool(tok["access_token"]), "после одобрения вход открыт")
        ok(await deps.user_from_access_token(tok["access_token"], db) is not None, "токен действует")

        await admin.block_user(anna.id, db=db, admin=owner)
        ok(await deps.user_from_access_token(tok["access_token"], db) is None, "блокировка отзывает токен сразу")
        await admin.unblock_user(anna.id, db=db, admin=owner)

        try:
            await admin.block_user(owner.id, db=db, admin=owner)
            ok(False, "себя заблокировать нельзя")
        except HTTPException as e:
            ok(e.status_code == 400, "админ не может заблокировать сам себя")

        temp = (await admin.reset_password(anna.id, db=db, admin=owner))["temporary_password"]
        await auth.login(UserLogin(username="anna", password=temp), Req(), Response(), db)
        await auth.change_password(PasswordChange(old_password=temp, new_password="N3w#Secret"), db=db, current_user=anna)
        tok = await auth.login(UserLogin(username="anna", password="N3w#Secret"), Req(), Response(), db)
        ok(bool(tok["access_token"]), "сброс пароля админом → вход временным → смена своего")

        # привязка Telegram
        link = await me.telegram_link(db=db, user=anna)
        bot = TelegramBot("test-token")
        reply = await bot.handle({"id": 555, "type": "private"}, "/start wrong-code")
        ok("не подошёл" in reply, "чужой код не привязывает")
        reply = await bot.handle({"id": 555, "type": "group"}, f"/start {link['code']}")
        ok("личный чат" in reply, "группу привязать нельзя")
        reply = await bot.handle({"id": 555, "type": "private"}, f"/start {link['code']}")
        await db.refresh(anna)
        ok("Подключено" in reply and anna.telegram_chat_id == "555", "код из настроек привязывает личный чат")
        reply = await bot.handle({"id": 555, "type": "private"}, f"/start {link['code']}")
        ok("не подошёл" in reply, "код одноразовый")

        link = await me.telegram_link(db=db, user=anna)
        anna.telegram_link_expires = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
        reply = await bot.handle({"id": 556, "type": "private"}, f"/start {link['code']}")
        ok("устарел" in reply, "просроченный код не подходит")

        info = await me.me(db=db, user=anna)
        ok(info["telegram"]["linked"] and info["bots"] == {"count": 0, "limit": 3}, "профиль: Telegram и лимит")

        # лимит ботов
        for i in range(3):
            db.add(Bot(user_id=anna.id, exchange="paper", name=f"b{i}", symbol="SOLUSDT", side="SHORT",
                       config={"order_count": 4}, state="IDLE"))
        await db.commit()
        try:
            await me.ensure_bot_capacity(db, anna)
            ok(False, "четвёртый бот при лимите 3")
        except HTTPException as e:
            ok(e.status_code == 403, "лимит ботов: 4-й бот — 403")
        await me.ensure_bot_capacity(db, owner, adding=50)
        ok(True, "у владельца лимита нет")

        # уведомление о сделке — в чат Анны, не владельца
        b0 = (await db.execute(select(Bot).where(Bot.user_id == anna.id))).scalars().first()
        sent.clear()
        tn.notifier._routes.clear()
        await tn.notifier._send_event("position_closed", {"bot_id": b0.id, "side": "SHORT", "symbol": "SOLUSDT",
                                                          "exit_reason": "TP_HIT", "pnl": 12.0})
        ok([p["chat_id"] for _, p in sent] == ["555"], "сделка бота Анны — в её чат, а не владельцу")

        # личный алерт: бот Анны выпал в IDLE из цикла
        b0.state, b0.config = "IDLE", {"order_count": 4, "cycle": True, "entry_signal": {"type": "supertrend"}}
        await db.commit()
        sent.clear()
        n = await ua.UserAlerts().check_once(now=1000.0)
        texts = [p["text"] for _, p in sent]
        ok(n >= 1 and all(p["chat_id"] == "555" for _, p in sent) and texts[0].startswith("🔴"),
           "алерт по боту Анны пришёл ей")

        await bot.handle({"id": 555, "type": "private"}, "/stop")
        await db.refresh(anna)
        ok(anna.telegram_chat_id is None, "/stop отвязывает")
    await close_redis()
    print("ALL OK")


if __name__ == "__main__":
    asyncio.run(main())
