from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List
from app.core.database import get_db
from app.models import User, Bot, Position
from app.schemas.bot import BotCreate, BotUpdate, BotResponse
from app.api.deps import get_current_user
from app.services.cryptorg import cryptorg_client

router = APIRouter()


@router.get("/", response_model=List[BotResponse])
async def get_bots(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all bots"""
    result = await db.execute(select(Bot).order_by(Bot.created_at.desc()))
    bots = result.scalars().all()
    return bots


@router.get("/cryptorg")
async def get_cryptorg_bots(
    current_user: User = Depends(get_current_user)
):
    """Get all bots from Cryptorg API"""
    bots = await cryptorg_client.get_all_bots()

    if bots is None:
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch bots from Cryptorg API"
        )

    return bots


@router.get("/{bot_id}", response_model=BotResponse)
async def get_bot(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get single bot"""
    result = await db.execute(select(Bot).where(Bot.id == bot_id))
    bot = result.scalar_one_or_none()

    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    return bot


@router.post("/", response_model=BotResponse)
async def create_bot(
    bot_data: BotCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create new bot"""
    bot = Bot(
        name=bot_data.name,
        symbol=bot_data.symbol,
        side=bot_data.side,
        config=bot_data.config.model_dump(),
        state="IDLE",
        is_active=False
    )

    db.add(bot)
    await db.commit()
    await db.refresh(bot)

    return bot


@router.patch("/{bot_id}", response_model=BotResponse)
async def update_bot(
    bot_id: int,
    bot_data: BotUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update bot"""
    result = await db.execute(select(Bot).where(Bot.id == bot_id))
    bot = result.scalar_one_or_none()

    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot_data.name is not None:
        bot.name = bot_data.name

    if bot_data.config is not None:
        bot.config = bot_data.config.model_dump()

    if bot_data.is_active is not None:
        bot.is_active = bot_data.is_active

    await db.commit()
    await db.refresh(bot)

    return bot


@router.delete("/{bot_id}")
async def delete_bot(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete bot"""
    result = await db.execute(select(Bot).where(Bot.id == bot_id))
    bot = result.scalar_one_or_none()

    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    # Check if bot has open positions
    result = await db.execute(
        select(Position).where(
            and_(Position.bot_id == bot_id, Position.is_open == True)
        )
    )
    open_position = result.scalar_one_or_none()

    if open_position:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete bot with open position"
        )

    await db.delete(bot)
    await db.commit()

    return {"success": True}
