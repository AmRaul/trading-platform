from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from app.core.database import get_db
from app.api.deps import get_admin_user
from app.models import User, Bot, Position, CryptorgAccount

router = APIRouter()


class AdminStats(BaseModel):
    users_total: int
    accounts_total: int
    bots_total: int
    bots_active: int
    positions_open: int


class AdminUserRow(BaseModel):
    id: int
    username: str
    email: Optional[str]
    is_active: bool
    plan: str
    created_at: datetime
    bots_count: int
    accounts_count: int

    class Config:
        from_attributes = True


class AdminBotRow(BaseModel):
    id: int
    owner_username: str
    name: str
    symbol: str
    side: str
    state: str
    is_active: bool
    total_pnl: float
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/stats", response_model=AdminStats)
async def get_admin_stats(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    users_total = (await db.execute(select(func.count(User.id)))).scalar_one()
    # Count only, never read/decrypt account rows — those hold encrypted
    # webhook_url/api_key/api_secret and have no business being touched by
    # an aggregate stats query.
    accounts_total = (await db.execute(select(func.count(CryptorgAccount.id)))).scalar_one()
    bots_total = (await db.execute(select(func.count(Bot.id)))).scalar_one()
    bots_active = (await db.execute(select(func.count(Bot.id)).where(Bot.is_active == True))).scalar_one()
    positions_open = (await db.execute(select(func.count(Position.id)).where(Position.is_open == True))).scalar_one()

    return AdminStats(
        users_total=users_total,
        accounts_total=accounts_total,
        bots_total=bots_total,
        bots_active=bots_active,
        positions_open=positions_open,
    )


@router.get("/users", response_model=List[AdminUserRow])
async def get_admin_users(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    users_result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = users_result.scalars().all()

    bots_by_user = dict(
        (await db.execute(
            select(Bot.user_id, func.count(Bot.id)).group_by(Bot.user_id)
        )).all()
    )
    # Same rule as /stats: count(*) only, never select the account rows themselves.
    accounts_by_user = dict(
        (await db.execute(
            select(CryptorgAccount.user_id, func.count(CryptorgAccount.id)).group_by(CryptorgAccount.user_id)
        )).all()
    )

    return [
        AdminUserRow(
            id=u.id,
            username=u.username,
            email=u.email,
            is_active=u.is_active,
            plan=u.plan,
            created_at=u.created_at,
            bots_count=bots_by_user.get(u.id, 0),
            accounts_count=accounts_by_user.get(u.id, 0),
        )
        for u in users
    ]


@router.get("/bots", response_model=List[AdminBotRow])
async def get_admin_bots(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    result = await db.execute(
        select(Bot, User.username)
        .join(User, User.id == Bot.user_id)
        .order_by(Bot.created_at.desc())
    )
    rows = result.all()

    return [
        AdminBotRow(
            id=bot.id,
            owner_username=username,
            name=bot.name,
            symbol=bot.symbol,
            side=bot.side,
            state=bot.state,
            is_active=bot.is_active,
            total_pnl=bot.total_pnl,
            created_at=bot.created_at,
        )
        for bot, username in rows
    ]
