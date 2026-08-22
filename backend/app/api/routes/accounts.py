from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models import User
from app.models.cryptorg_account import CryptorgAccount
from app.core.encryption import encrypt, decrypt

router = APIRouter()


class AccountCreate(BaseModel):
    name: str
    webhook_url: str
    api_key: Optional[str] = None
    api_secret: Optional[str] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    webhook_url: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None


class AccountResponse(BaseModel):
    id: int
    name: str
    webhook_url_hint: str
    has_api_key: bool
    has_api_secret: bool

    class Config:
        from_attributes = True


@router.get("/", response_model=List[AccountResponse])
async def get_accounts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(CryptorgAccount).where(CryptorgAccount.user_id == current_user.id)
    )
    accounts = result.scalars().all()
    return [
        AccountResponse(
            id=a.id,
            name=a.name,
            webhook_url_hint="..." + decrypt(a.webhook_url)[-8:],
            has_api_key=bool(a.api_key),
            has_api_secret=bool(a.api_secret),
        )
        for a in accounts
    ]


@router.post("/", response_model=AccountResponse)
async def create_account(
    data: AccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = CryptorgAccount(
        user_id=current_user.id,
        name=data.name,
        webhook_url=encrypt(data.webhook_url),
        api_key=encrypt(data.api_key) if data.api_key else None,
        api_secret=encrypt(data.api_secret) if data.api_secret else None,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return AccountResponse(
        id=account.id,
        name=account.name,
        webhook_url_hint="..." + data.webhook_url[-8:],
        has_api_key=bool(data.api_key),
        has_api_secret=bool(data.api_secret),
    )


@router.put("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: int,
    data: AccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(CryptorgAccount).where(
            CryptorgAccount.id == account_id,
            CryptorgAccount.user_id == current_user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if data.name is not None:
        account.name = data.name
    if data.webhook_url is not None:
        account.webhook_url = encrypt(data.webhook_url)
    if data.api_key is not None:
        account.api_key = encrypt(data.api_key)
    if data.api_secret is not None:
        account.api_secret = encrypt(data.api_secret)

    await db.commit()
    await db.refresh(account)
    webhook_hint = "..." + decrypt(account.webhook_url)[-8:]
    return AccountResponse(
        id=account.id,
        name=account.name,
        webhook_url_hint=webhook_hint,
        has_api_key=bool(account.api_key),
        has_api_secret=bool(account.api_secret),
    )


@router.delete("/{account_id}")
async def delete_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(CryptorgAccount).where(
            CryptorgAccount.id == account_id,
            CryptorgAccount.user_id == current_user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    await db.delete(account)
    await db.commit()
    return {"ok": True}
