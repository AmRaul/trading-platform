from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Get current authenticated user"""
    token = credentials.credentials
    payload = decode_access_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return user


async def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """Single-owner admin gate — no role system, just a username match
    against ADMIN_USERNAME. Empty ADMIN_USERNAME denies everyone (fails
    closed, not open) so an unconfigured deploy doesn't accidentally expose
    /api/admin/* to whoever's username happens to be an empty string.
    """
    if not settings.ADMIN_USERNAME or current_user.username != settings.ADMIN_USERNAME:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
