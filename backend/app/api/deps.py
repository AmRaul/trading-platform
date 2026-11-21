from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User

# auto_error=False: без токена — 401 (фронтенд уводит на вход), а не 403 по умолчанию FastAPI
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Get current authenticated user"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await user_from_access_token(credentials.credentials, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def user_from_access_token(token: Optional[str], db: AsyncSession) -> Optional[User]:
    """Пользователь по access-токену или None (нет токена, подпись/срок/тип не те, юзера нет).
    Общая проверка для HTTP (get_current_user) и WebSocket (первое сообщение auth)."""
    payload = decode_access_token(token) if token else None
    username = payload.get("sub") if payload else None
    if not username:
        return None
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None or access_denied_reason(user):
        return None  # заблокирован или ещё не одобрен — токен больше не действует
    return user


def access_denied_reason(user: User) -> Optional[str]:
    """Почему пользователю закрыт вход; None — открыт. Админ (ADMIN_USERNAME) входит всегда:
    иначе ошибка в базе заперла бы владельца из его же платформы."""
    if is_admin(user):
        return None
    if user.is_active is False:
        return "Доступ закрыт администратором"
    if not user.approved:
        return "Заявка на регистрацию ждёт одобрения администратора"
    return None


async def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """Single-owner admin gate — no role system, just a username match
    against ADMIN_USERNAME. Empty ADMIN_USERNAME denies everyone (fails
    closed, not open) so an unconfigured deploy doesn't accidentally expose
    /api/admin/* to whoever's username happens to be an empty string.
    """
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def is_admin(user: User) -> bool:
    return bool(settings.ADMIN_USERNAME) and user.username == settings.ADMIN_USERNAME
