from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Sequence
from app.core.database import get_db
from app.core.redis import get_position_state
from app.models import User, Bot, Position
from app.schemas.position import PositionResponse, PositionManagedUpdate
from app.api.deps import get_current_user

router = APIRouter()


async def _apply_live_state(positions: Sequence[Position]) -> Sequence[Position]:
    """Overlay live unrealized_pnl/current_sl from Redis onto open positions.

    handle_price_update.py only writes per-tick PnL/SL to Redis (Postgres
    commits happen on entry/pyramiding/close), so reading straight from the
    DB shows stale — often $0.00 — values for a position that hasn't
    triggered another order yet.
    """
    for pos in positions:
        if not pos.is_open:
            continue
        state = await get_position_state(str(pos.bot_id))
        if not state:
            continue
        if "unrealized_pnl" in state:
            pos.unrealized_pnl = state["unrealized_pnl"]
        if "current_sl" in state:
            pos.current_sl = state["current_sl"]
    return positions


@router.get("/", response_model=List[PositionResponse])
async def get_positions(
    is_open: bool = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = (
        select(Position)
        .join(Bot, Bot.id == Position.bot_id)
        .where(Bot.user_id == current_user.id)
    )
    if is_open is not None:
        query = query.where(Position.is_open == is_open)
    query = query.order_by(Position.opened_at.desc())

    result = await db.execute(query)
    return await _apply_live_state(result.scalars().all())


@router.get("/bot/{bot_id}", response_model=List[PositionResponse])
async def get_bot_positions(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Position)
        .join(Bot, Bot.id == Position.bot_id)
        .where(Position.bot_id == bot_id, Bot.user_id == current_user.id)
        .order_by(Position.opened_at.desc())
    )
    return await _apply_live_state(result.scalars().all())


@router.patch("/{position_id}/managed", response_model=PositionResponse)
async def set_position_managed(
    position_id: int,
    data: PositionManagedUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Toggle bot management of a position.

    is_bot_managed=False: the bot stops touching this position entirely
    (no SL checks, no pyramiding, no trailing SL/PnL updates) so the user
    can take over manually — e.g. on the exchange directly. The position
    stays visible here (still is_open) but the bot no longer acts on it.
    """
    result = await db.execute(
        select(Position)
        .join(Bot, Bot.id == Position.bot_id)
        .where(Position.id == position_id, Bot.user_id == current_user.id)
    )
    position = result.scalar_one_or_none()

    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    if not position.is_open:
        raise HTTPException(status_code=400, detail="Position is already closed")

    position.is_bot_managed = data.is_bot_managed
    await db.commit()
    await db.refresh(position)

    # If the bot is currently live (registered with the price stream), update
    # the in-memory engine's position too — StrategyEngine holds its own
    # long-lived DB session/object, so a plain DB commit here won't be seen
    # by that session until it's asked to refresh. Single-threaded asyncio
    # event loop, so this is race-free.
    from app.services.websocket import price_stream_manager
    engine = price_stream_manager.strategy_engines.get(position.bot_id)
    if engine and engine.position and engine.position.id == position.id:
        engine.position.is_bot_managed = data.is_bot_managed

    return position
