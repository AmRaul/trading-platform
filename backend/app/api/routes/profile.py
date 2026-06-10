from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from app.core.database import get_db
from app.models import User
from app.models.user_credential import UserCredential
from app.api.deps import get_current_user
from app.core.encryption import encrypt, decrypt

router = APIRouter()


class CredentialCreate(BaseModel):
    exchange: str = "cryptorg"
    webhook_url: str
    api_key: Optional[str] = None
    api_secret: Optional[str] = None


class CredentialResponse(BaseModel):
    exchange: str
    webhook_url_hint: str  # only last 8 chars
    has_api_key: bool
    has_api_secret: bool

    class Config:
        from_attributes = True


@router.get("/credentials", response_model=Optional[CredentialResponse])
async def get_credentials(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(UserCredential).where(UserCredential.user_id == current_user.id)
    )
    cred = result.scalar_one_or_none()
    if not cred:
        return None
    return CredentialResponse(
        exchange=cred.exchange,
        webhook_url_hint="..." + decrypt(cred.webhook_url)[-8:],
        has_api_key=bool(cred.api_key),
        has_api_secret=bool(cred.api_secret),
    )


@router.put("/credentials", response_model=CredentialResponse)
async def upsert_credentials(
    data: CredentialCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(UserCredential).where(UserCredential.user_id == current_user.id)
    )
    cred = result.scalar_one_or_none()

    if cred:
        cred.exchange = data.exchange
        cred.webhook_url = encrypt(data.webhook_url)
        if data.api_key:
            cred.api_key = encrypt(data.api_key)
        if data.api_secret:
            cred.api_secret = encrypt(data.api_secret)
    else:
        cred = UserCredential(
            user_id=current_user.id,
            exchange=data.exchange,
            webhook_url=encrypt(data.webhook_url),
            api_key=encrypt(data.api_key) if data.api_key else None,
            api_secret=encrypt(data.api_secret) if data.api_secret else None,
        )
        db.add(cred)

    await db.flush()
    return CredentialResponse(
        exchange=cred.exchange,
        webhook_url_hint="..." + data.webhook_url[-8:],
        has_api_key=bool(data.api_key),
        has_api_secret=bool(data.api_secret),
    )
