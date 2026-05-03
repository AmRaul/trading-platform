from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List
from app.core.database import get_db
from app.models import User, Bot, Position, Order, Trade
from app.schemas.bot import BotCreate, BotUpdate, BotResponse, OpenPositionData
from app.api.deps import get_current_user
from app.services.cryptorg import cryptorg_client
from app.core.redis import get_position_state

router = APIRouter()


@router.get("/", response_model=List[BotResponse])
async def get_bots(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all bots"""
    result = await db.execute(select(Bot).order_by(Bot.created_at.desc()))
    bots = result.scalars().all()

    # Fetch open positions for active bots
    active_bot_ids = [b.id for b in bots if b.state != "IDLE"]
    positions_by_bot = {}
    if active_bot_ids:
        pos_result = await db.execute(
            select(Position).where(
                and_(
                    Position.bot_id.in_(active_bot_ids),
                    Position.is_open == True
                )
            )
        )
        for pos in pos_result.scalars().all():
            positions_by_bot[pos.bot_id] = pos

    # Get last_order_price per bot (Redis first, then DB fallback)
    last_order_prices = {}
    for bot_id, pos in positions_by_bot.items():
        redis_state = await get_position_state(str(bot_id))
        if redis_state and redis_state.get("last_order_price"):
            last_order_prices[bot_id] = redis_state["last_order_price"]
        else:
            order_result = await db.execute(
                select(Order.price)
                .where(
                    and_(
                        Order.position_id == pos.id,
                        Order.status == "FILLED"
                    )
                )
                .order_by(Order.order_number.desc())
                .limit(1)
            )
            last_order_prices[bot_id] = order_result.scalar_one_or_none()

    # Assemble response with open_position
    response = []
    for bot in bots:
        pos = positions_by_bot.get(bot.id)
        open_position = None
        if pos:
            open_position = OpenPositionData(
                average_price=pos.average_price,
                current_sl=pos.current_sl,
                total_size=pos.total_size,
                order_count=pos.order_count,
                unrealized_pnl=pos.unrealized_pnl or 0.0,
                last_order_price=last_order_prices.get(bot.id),
                opened_at=pos.opened_at,
            )
        response.append(BotResponse(
            id=bot.id,
            name=bot.name,
            symbol=bot.symbol,
            side=bot.side,
            config=bot.config,
            state=bot.state,
            is_active=bot.is_active,
            total_pnl=bot.total_pnl,
            created_at=bot.created_at,
            started_at=bot.started_at,
            open_position=open_position,
        ))

    return response


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

    # Delete child records in order: orders → trades → positions → bot
    orders = await db.execute(select(Order).where(Order.bot_id == bot_id))
    for order in orders.scalars().all():
        await db.delete(order)
    await db.flush()

    trades = await db.execute(select(Trade).where(Trade.bot_id == bot_id))
    for trade in trades.scalars().all():
        await db.delete(trade)
    await db.flush()

    positions = await db.execute(select(Position).where(Position.bot_id == bot_id))
    for position in positions.scalars().all():
        await db.delete(position)
    await db.flush()

    await db.delete(bot)
    await db.commit()

    return {"success": True}
