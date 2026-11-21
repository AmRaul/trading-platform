"""Приём сообщений боту Telegram — только для привязки личного чата.

Пользователь жмёт «Подключить Telegram» в настройках kandle → получает одноразовый код
и ссылку t.me/<бот>?start=<код> → бот получает «/start <код>» и записывает chat_id
пользователю. «/stop» — отвязать. Читаем getUpdates (long polling): других читателей
у бота нет — алертер и бэкапы только отправляют.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

POLL_TIMEOUT_SEC = 50

HELP = ("Это бот уведомлений kandle. Чтобы подключить его к своему аккаунту, откройте kandle → "
        "Настройки → «Подключить Telegram». Отключить — /stop.")


class TelegramBot:
    def __init__(self, token: str = ""):
        self.token = token
        self.username: Optional[str] = None  # @имя бота — для ссылки t.me/<имя>?start=<код>
        self._offset = 0
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self.token and (not self._task or self._task.done()):
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        from app.services.telegram_notifier import telegram_call
        delay = 5
        while True:
            try:
                if not self.username:
                    me = await telegram_call(self.token, "getMe", {})
                    self.username = (me or {}).get("username")
                updates = await telegram_call(self.token, "getUpdates", {
                    "offset": self._offset, "timeout": POLL_TIMEOUT_SEC, "allowed_updates": ["message"],
                }, timeout=POLL_TIMEOUT_SEC)
                if updates is None:  # сеть, 409 (бота читает кто-то ещё) — пауза
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 300)
                    continue
                delay = 5
                for upd in updates:
                    self._offset = max(self._offset, upd["update_id"] + 1)
                    msg = upd.get("message") or {}
                    if msg.get("text"):
                        reply = await self.handle(msg["chat"], msg["text"])
                        if reply:
                            await telegram_call(self.token, "sendMessage", {"chat_id": msg["chat"]["id"], "text": reply})
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[TelegramBot] {e}", exc_info=True)
                await asyncio.sleep(delay)

    async def handle(self, chat: dict, text: str, now: Optional[datetime] = None) -> Optional[str]:
        """Ответ на сообщение (None — молчим)."""
        from app.models import User
        from app.services.telegram_notifier import notifier

        now = now or datetime.now(timezone.utc)
        parts = text.strip().split()
        command = parts[0].split("@")[0].lower() if parts else ""
        chat_id = str(chat.get("id"))

        if command == "/start" and len(parts) > 1:
            if chat.get("type") != "private":
                return "Подключить можно только личный чат с ботом."
            async with AsyncSessionLocal() as db:
                user = (await db.execute(select(User).where(User.telegram_link_code == parts[1]))).scalar_one_or_none()
                expires = user.telegram_link_expires if user else None
                if expires is not None and expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if not user or not expires or expires < now:
                    return "Код не подошёл или устарел. Получите новый в kandle → Настройки → «Подключить Telegram»."
                user.telegram_chat_id = chat_id
                user.telegram_link_code = None
                user.telegram_link_expires = None
                await db.commit()
                notifier.forget_user(user.id)
                return (f"✅ Подключено к kandle: {user.username}.\n"
                        "Сюда будут приходить входы, доборы, выходы и проблемы ваших ботов. Отключить — /stop.")

        if command == "/stop":
            async with AsyncSessionLocal() as db:
                users = (await db.execute(select(User).where(User.telegram_chat_id == chat_id))).scalars().all()
                for u in users:
                    u.telegram_chat_id = None
                    notifier.forget_user(u.id)
                await db.commit()
            return "Отключено: уведомления kandle сюда больше не приходят." if users else HELP

        return HELP


telegram_bot = TelegramBot(settings.TELEGRAM_BOT_TOKEN)
