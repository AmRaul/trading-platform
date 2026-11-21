"""Личные алерты пользователей по их ботам: раз в INTERVAL_SEC — bots-health каждого
пользователя с привязанным Telegram, и в его чат — что появилось, что ушло, напоминание.

Владельца платформы (ADMIN_USERNAME) не трогаем: его ботов и сам бэкенд сторожит отдельный
контейнер services/alerter — он сообщит и тогда, когда бэкенд лежит (а этот цикл — нет).
"""
import asyncio
import logging
import time
from typing import Dict, Optional

from sqlalchemy import and_, select

from app.application.monitoring.alert_state import AlertState, bot_problems
from app.core.config import settings
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

INTERVAL_SEC = 300


class UserAlerts:
    def __init__(self, interval: float = INTERVAL_SEC):
        self.interval = interval
        self.states: Dict[int, AlertState] = {}
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if settings.TELEGRAM_BOT_TOKEN and (not self._task or self._task.done()):
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        await asyncio.sleep(180)  # первые минуты после рестарта bots-health сам не ругается на тики
        while True:
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[UserAlerts] {e}", exc_info=True)
            await asyncio.sleep(self.interval)

    async def check_once(self, now: Optional[float] = None) -> int:
        """Возвращает число отправленных сообщений."""
        from app.api.routes.analytics import build_bots_health
        from app.models import User
        from app.services.telegram_notifier import notifier, telegram_call

        now = now or time.time()
        sent = 0
        async with AsyncSessionLocal() as db:
            users = (await db.execute(select(User).where(and_(
                User.telegram_chat_id.isnot(None), User.username != (settings.ADMIN_USERNAME or ""))))).scalars().all()
            for u in users:
                route = notifier.route_for(u)  # заблокированным/неодобренным и с режимом off — не шлём
                if not route:
                    self.states.pop(u.id, None)
                    continue
                report = await build_bots_health(db, u.id)
                state = self.states.setdefault(u.id, AlertState())
                for text in state.update(bot_problems(report), now):
                    if await telegram_call(settings.TELEGRAM_BOT_TOKEN, "sendMessage",
                                           {"chat_id": route[0], "text": text}) is not None:
                        sent += 1
        return sent


user_alerts = UserAlerts()
