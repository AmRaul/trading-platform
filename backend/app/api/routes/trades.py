from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from app.core.database import get_db
from app.models import User, Bot, Trade
from app.schemas.trade import TradeResponse
from app.api.deps import get_current_user

router = APIRouter()


@router.get("/", response_model=List[TradeResponse])
async def get_trades(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Trade)
        .join(Bot, Bot.id == Trade.bot_id)
        .where(Bot.user_id == current_user.id)
        .order_by(Trade.closed_at.desc())
        .limit(100)
    )
    return result.scalars().all()


@router.get("/bot/{bot_id}", response_model=List[TradeResponse])
async def get_bot_trades(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Trade)
        .join(Bot, Bot.id == Trade.bot_id)
        .where(Trade.bot_id == bot_id, Bot.user_id == current_user.id)
        .order_by(Trade.closed_at.desc())
    )
    return result.scalars().all()
