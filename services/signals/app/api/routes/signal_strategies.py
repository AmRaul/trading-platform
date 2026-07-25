from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import List, Optional

from app.core.database import get_db
from app.models.signal_strategy import SignalStrategy

router = APIRouter()


class StrategyCreate(BaseModel):
    name: str
    range_min: Optional[float] = None
    range_max: Optional[float] = None
    change_min: Optional[float] = None
    change_max: Optional[float] = None
    vol_1h_min: Optional[float] = None
    side: str = "LONG"
    description: Optional[str] = None


class StrategyUpdate(BaseModel):
    range_min: Optional[float] = None
    range_max: Optional[float] = None
    change_min: Optional[float] = None
    change_max: Optional[float] = None
    vol_1h_min: Optional[float] = None
    side: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class StrategyResponse(BaseModel):
    id: int
    name: str
    is_builtin: bool
    is_active: bool
    range_min: Optional[float]
    range_max: Optional[float]
    change_min: Optional[float]
    change_max: Optional[float]
    vol_1h_min: Optional[float]
    side: str
    description: Optional[str]

    class Config:
        from_attributes = True


@router.get("/", response_model=List[StrategyResponse])
async def get_strategies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SignalStrategy).order_by(SignalStrategy.is_builtin.desc(), SignalStrategy.name))
    return result.scalars().all()


@router.post("/", response_model=StrategyResponse)
async def create_strategy(data: StrategyCreate, db: AsyncSession = Depends(get_db)):
    name = data.name.upper().strip()
    existing = await db.execute(select(SignalStrategy).where(SignalStrategy.name == name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Strategy with this name already exists")
    strategy = SignalStrategy(
        name=name,
        is_builtin=False,
        is_active=True,
        range_min=data.range_min,
        range_max=data.range_max,
        change_min=data.change_min,
        change_max=data.change_max,
        vol_1h_min=data.vol_1h_min,
        side=data.side.upper(),
        description=data.description,
    )
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    return strategy


@router.patch("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(strategy_id: int, data: StrategyUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SignalStrategy).where(SignalStrategy.id == strategy_id))
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    if strategy.is_builtin:
        raise HTTPException(status_code=403, detail="Cannot modify built-in strategy")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(strategy, field, value)
    await db.commit()
    await db.refresh(strategy)
    return strategy


@router.delete("/{strategy_id}")
async def delete_strategy(strategy_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SignalStrategy).where(SignalStrategy.id == strategy_id))
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    if strategy.is_builtin:
        raise HTTPException(status_code=403, detail="Cannot delete built-in strategy")
    await db.delete(strategy)
    await db.commit()
    return {"success": True}
