from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import logging

from app.core.config import settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.api.deps import get_admin_user
from app.models import User, Bot, Position, CryptorgAccount

logger = logging.getLogger(__name__)

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


class DesyncedBot(BaseModel):
    bot_id: int
    symbol: str
    state: str
    owner_username: str


class AdminHealth(BaseModel):
    redis_ok: bool
    redis_error: Optional[str] = None
    price_tracker_ok: bool
    price_tracker_error: Optional[str] = None
    price_tracker_subscriptions: dict
    registered_bots_count: int
    db_active_bots_count: int
    desynced_bots: List[DesyncedBot]


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


@router.get("/health", response_model=AdminHealth)
async def get_admin_health(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    # Redis
    redis_ok = False
    redis_error = None
    try:
        redis = await get_redis()
        await redis.ping()
        redis_ok = True
    except Exception as e:
        redis_error = str(e)

    # price-tracker service
    price_tracker_ok = False
    price_tracker_error = None
    price_tracker_subscriptions: dict = {}
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{settings.PRICE_TRACKER_URL}/health", timeout=aiohttp.ClientTimeout(total=5)) as r:
                price_tracker_ok = r.status == 200
            async with session.get(f"{settings.PRICE_TRACKER_URL}/subscriptions", timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status == 200:
                    price_tracker_subscriptions = await r.json()
    except Exception as e:
        price_tracker_error = str(e)

    # DB vs in-memory registration desync — the exact class of bug that
    # silently drops WAITING/PYRAMIDING bots from price_stream_manager
    # (e.g. after an unwanted process reload) without touching bot.state
    # in Postgres, so the two sources of truth quietly diverge.
    from app.services.websocket import price_stream_manager

    active_result = await db.execute(
        select(Bot, User.username)
        .join(User, User.id == Bot.user_id)
        .where(Bot.state.in_(["WAITING", "PYRAMIDING"]))
    )
    active_rows = active_result.all()

    desynced_bots = [
        DesyncedBot(bot_id=bot.id, symbol=bot.symbol, state=bot.state, owner_username=username)
        for bot, username in active_rows
        if bot.id not in price_stream_manager.registered_bots
    ]

    return AdminHealth(
        redis_ok=redis_ok,
        redis_error=redis_error,
        price_tracker_ok=price_tracker_ok,
        price_tracker_error=price_tracker_error,
        price_tracker_subscriptions=price_tracker_subscriptions,
        registered_bots_count=len(price_stream_manager.registered_bots),
        db_active_bots_count=len(active_rows),
        desynced_bots=desynced_bots,
    )
