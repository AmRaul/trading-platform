"""Настройки текущего пользователя: профиль, личный Telegram, лимиты."""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, is_admin
from app.core.config import settings
from app.core.database import get_db
from app.models import Bot, User

router = APIRouter()

LINK_CODE_TTL = timedelta(minutes=15)


def bot_limit(user: User):
    """Лимит ботов пользователя; None — без лимита (админ)."""
    return None if is_admin(user) else settings.MAX_BOTS_PER_USER


async def bots_count(db: AsyncSession, user_id: int) -> int:
    return (await db.execute(select(func.count(Bot.id)).where(Bot.user_id == user_id))).scalar() or 0


async def ensure_bot_capacity(db: AsyncSession, user: User, adding: int = 1) -> None:
    """403, если новые боты не влезут в лимит."""
    limit = bot_limit(user)
    if limit is None:
        return
    have = await bots_count(db, user.id)
    if have + adding > limit:
        raise HTTPException(status_code=403, detail=(
            f"Лимит ботов: {limit}. Сейчас {have}, добавить {adding} нельзя — удалите ненужных ботов"))


def _telegram(user: User) -> dict:
    from app.services.telegram_bot import telegram_bot
    owner_fallback = is_admin(user) and not user.telegram_chat_id and bool(settings.TELEGRAM_CHAT_ID)
    return {
        "available": bool(settings.TELEGRAM_BOT_TOKEN),
        "linked": bool(user.telegram_chat_id) or owner_fallback,
        # владелец без своей привязки получает в общий чат TELEGRAM_CHAT_ID
        "via_owner_chat": owner_fallback,
        "notify": user.telegram_notify or "all",
        "bot_username": telegram_bot.username,
    }


@router.get("")
async def me(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return {
        "username": user.username,
        "is_admin": is_admin(user),
        "telegram": _telegram(user),
        "bots": {"count": await bots_count(db, user.id), "limit": bot_limit(user)},
    }


@router.post("/telegram/link")
async def telegram_link(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Одноразовый код (15 мин) и ссылка на бота: «Start» в Telegram привязывает чат."""
    from app.services.telegram_bot import telegram_bot
    if not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=503, detail="Telegram-бот на сервере не настроен")
    user.telegram_link_code = secrets.token_urlsafe(12)
    user.telegram_link_expires = datetime.now(timezone.utc) + LINK_CODE_TTL
    await db.commit()
    url = f"https://t.me/{telegram_bot.username}?start={user.telegram_link_code}" if telegram_bot.username else None
    return {"code": user.telegram_link_code, "url": url, "expires_at": user.telegram_link_expires,
            "bot_username": telegram_bot.username}


class TelegramSettings(BaseModel):
    notify: str = Field(pattern="^(all|real|off)$")


@router.put("/telegram")
async def telegram_settings(data: TelegramSettings, db: AsyncSession = Depends(get_db),
                            user: User = Depends(get_current_user)):
    from app.services.telegram_notifier import notifier
    user.telegram_notify = data.notify
    await db.commit()
    notifier.forget_user(user.id)
    return _telegram(user)


@router.delete("/telegram")
async def telegram_unlink(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from app.services.telegram_notifier import notifier
    user.telegram_chat_id = None
    user.telegram_link_code = None
    await db.commit()
    notifier.forget_user(user.id)
    return _telegram(user)
