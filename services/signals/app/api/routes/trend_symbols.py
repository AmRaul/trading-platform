from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import List

from app.core.database import get_db
from app.models.trend_symbol import TrendSymbol

router = APIRouter()


class TrendSymbolCreate(BaseModel):
    symbol: str


class TrendSymbolResponse(BaseModel):
    id: int
    symbol: str
    is_active: bool

    class Config:
        from_attributes = True


@router.get("/", response_model=List[TrendSymbolResponse])
async def get_trend_symbols(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TrendSymbol).where(TrendSymbol.is_active == True).order_by(TrendSymbol.symbol)
    )
    return result.scalars().all()


@router.post("/", response_model=TrendSymbolResponse)
async def add_trend_symbol(data: TrendSymbolCreate, db: AsyncSession = Depends(get_db)):
    symbol = data.symbol.upper().strip()
    existing = await db.execute(select(TrendSymbol).where(TrendSymbol.symbol == symbol))
    row = existing.scalar_one_or_none()
    if row:
        if not row.is_active:
            row.is_active = True
            await db.commit()
            await db.refresh(row)
            return row
        raise HTTPException(status_code=400, detail="Symbol already exists")
    new_symbol = TrendSymbol(symbol=symbol, is_active=True)
    db.add(new_symbol)
    await db.commit()
    await db.refresh(new_symbol)
    return new_symbol


@router.delete("/{symbol_id}")
async def remove_trend_symbol(symbol_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TrendSymbol).where(TrendSymbol.id == symbol_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Symbol not found")
    await db.delete(row)
    await db.commit()
    return {"success": True}
