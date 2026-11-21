from fastapi import APIRouter, Depends, HTTPException, Query
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


@router.post("/{account_id}/check")
async def check_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Проверить ключ Bybit счёта Cryptorg: работает ли и какие позиции видны.
    С рабочим ключом бот подтверждает каждый ордер позицией на бирже."""
    from app.adapters.executor_factory import cryptorg_reader

    result = await db.execute(
        select(CryptorgAccount).where(
            CryptorgAccount.id == account_id,
            CryptorgAccount.user_id == current_user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    reader = cryptorg_reader(account)
    if not reader:
        return {"ok": False, "error": "Ключ Bybit не задан — ордера Cryptorg не проверяются"}
    return await reader.check_key()


# Закрытая сделка Bybit и сделка бота — одна и та же, если совпали монета, сторона и время закрытия
MATCH_WINDOW_MS = 10 * 60 * 1000


@router.get("/{account_id}/exchange")
async def account_exchange(
    account_id: int,
    days: int = Query(30, ge=1, le=180),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Счёт Cryptorg глазами биржи (ключ Bybit «только чтение»): все открытые позиции и
    закрытые сделки за days дней, включая ручные. bot — какой бот ведёт/вёл сделку
    (None — не наш бот: вручную или другой бот Cryptorg). Ничего не меняет."""
    from app.adapters.executor_factory import cryptorg_reader
    from app.models import Bot, Position, Trade

    account = (await db.execute(select(CryptorgAccount).where(
        CryptorgAccount.id == account_id, CryptorgAccount.user_id == current_user.id))).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    reader = cryptorg_reader(account)
    if not reader:
        return {"ok": False, "error": "Ключ Bybit не задан — счёт не виден"}
    data = await reader.account_overview(days=days)
    if not data.get("ok"):
        return data

    bots = (await db.execute(select(Bot).where(
        Bot.user_id == current_user.id, Bot.exchange == "cryptorg", Bot.account_id == account_id))).scalars().all()
    by_id = {b.id: b for b in bots}
    open_by_key = {}
    trades = []
    if bots:
        for p in (await db.execute(select(Position).where(
                Position.bot_id.in_(list(by_id)), Position.is_open == True))).scalars().all():  # noqa: E712
            b = by_id[p.bot_id]
            open_by_key[(b.symbol, b.side)] = {"bot_id": b.id, "name": b.name, "position_id": p.id}
        trades = (await db.execute(select(Trade).where(Trade.bot_id.in_(list(by_id))))).scalars().all()

    for pos in data["positions"]:
        pos["bot"] = open_by_key.get((pos["symbol"], pos["side"]))
    used = set()
    for c in data["closed"]:
        c["bot"] = None
        for t in trades:
            if t.id in used or t.symbol != c["symbol"] or t.side != c["side"] or not t.closed_at:
                continue
            if abs(int(t.closed_at.timestamp() * 1000) - c["closed_at_ms"]) <= MATCH_WINDOW_MS:
                b = by_id[t.bot_id]
                c["bot"] = {"bot_id": b.id, "name": b.name, "trade_id": t.id}
                used.add(t.id)
                break

    def _sum(rows, bot):
        picked = [r for r in rows if (r["bot"] is not None) == bot]
        return {"count": len(picked), "pnl": round(sum(r["pnl"] for r in picked), 2)}

    data["summary"] = {
        "open_positions": len(data["positions"]),
        "open_unrealized_pnl": round(sum(p["unrealized_pnl"] for p in data["positions"]), 2),
        "closed": {"count": len(data["closed"]), "pnl": round(sum(c["pnl"] for c in data["closed"]), 2),
                   "by_bots": _sum(data["closed"], True), "not_bots": _sum(data["closed"], False)},
    }
    data["account"] = {"id": account.id, "name": account.name}
    return data
