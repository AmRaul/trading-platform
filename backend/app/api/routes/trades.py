from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from app.core.database import get_db
from app.models import User, Trade
from app.schemas.trade import TradeResponse
from app.api.deps import get_current_user

router = APIRouter()


@router.get("/", response_model=List[TradeResponse])
async def get_trades(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all trades"""
    result = await db.execute(
        select(Trade).order_by(Trade.closed_at.desc()).limit(100)
    )
    trades = result.scalars().all()

    return trades


@router.get("/bot/{bot_id}", response_model=List[TradeResponse])
async def get_bot_trades(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get trades for specific bot"""
    result = await db.execute(
        select(Trade)
        .where(Trade.bot_id == bot_id)
        .order_by(Trade.closed_at.desc())
    )
    trades = result.scalars().all()

    return trades
