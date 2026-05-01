from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List
from app.core.database import get_db
from app.models import User, Position
from app.schemas.position import PositionResponse
from app.api.deps import get_current_user

router = APIRouter()


@router.get("/", response_model=List[PositionResponse])
async def get_positions(
    is_open: bool = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get positions"""
    query = select(Position)

    if is_open is not None:
        query = query.where(Position.is_open == is_open)

    query = query.order_by(Position.opened_at.desc())

    result = await db.execute(query)
    positions = result.scalars().all()

    return positions


@router.get("/bot/{bot_id}", response_model=List[PositionResponse])
async def get_bot_positions(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get positions for specific bot"""
    result = await db.execute(
        select(Position)
        .where(Position.bot_id == bot_id)
        .order_by(Position.opened_at.desc())
    )
    positions = result.scalars().all()

    return positions
