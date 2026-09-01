from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models import User
from app.models.bybit_account import BybitAccount
from app.core.encryption import encrypt, decrypt

router = APIRouter()


class BybitAccountCreate(BaseModel):
    name: str
    api_key: str
    api_secret: str
    testnet: bool = False


class BybitAccountUpdate(BaseModel):
    name: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    testnet: Optional[bool] = None


class BybitAccountResponse(BaseModel):
    id: int
    name: str
    api_key_hint: str
    testnet: bool

    class Config:
        from_attributes = True


def _hint(decrypted_key: str) -> str:
    return "..." + decrypted_key[-6:] if len(decrypted_key) > 6 else "..."


@router.get("/", response_model=List[BybitAccountResponse])
async def get_bybit_accounts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(BybitAccount).where(BybitAccount.user_id == current_user.id)
    )
    accounts = result.scalars().all()
    return [
        BybitAccountResponse(
            id=a.id,
            name=a.name,
            api_key_hint=_hint(decrypt(a.api_key)),
            testnet=a.testnet,
        )
        for a in accounts
    ]


@router.post("/", response_model=BybitAccountResponse)
async def create_bybit_account(
    data: BybitAccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = BybitAccount(
        user_id=current_user.id,
        name=data.name,
        api_key=encrypt(data.api_key),
        api_secret=encrypt(data.api_secret),
        testnet=data.testnet,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return BybitAccountResponse(
        id=account.id,
        name=account.name,
        api_key_hint=_hint(data.api_key),
        testnet=account.testnet,
    )


@router.put("/{account_id}", response_model=BybitAccountResponse)
async def update_bybit_account(
    account_id: int,
    data: BybitAccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(BybitAccount).where(
            BybitAccount.id == account_id,
            BybitAccount.user_id == current_user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if data.name is not None:
        account.name = data.name
    if data.api_key is not None:
        account.api_key = encrypt(data.api_key)
    if data.api_secret is not None:
        account.api_secret = encrypt(data.api_secret)
    if data.testnet is not None:
        account.testnet = data.testnet

    await db.commit()
    await db.refresh(account)
    return BybitAccountResponse(
        id=account.id,
        name=account.name,
        api_key_hint=_hint(decrypt(account.api_key)),
        testnet=account.testnet,
    )


@router.delete("/{account_id}")
async def delete_bybit_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(BybitAccount).where(
            BybitAccount.id == account_id,
            BybitAccount.user_id == current_user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    await db.delete(account)
    await db.commit()
    return {"ok": True}
