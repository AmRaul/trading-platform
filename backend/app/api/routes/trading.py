from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.database import get_db
from sqlalchemy import select
from app.models import User, Bot
from app.services.strategy import StrategyEngine
from app.api.deps import get_current_user

router = APIRouter()


async def _owned_engine(bot_id: int, db: AsyncSession, user: User) -> StrategyEngine:
    """StrategyEngine только для бота текущего пользователя — чужой бот выглядит
    как несуществующий (404), чтобы не раскрывать, какие id заняты."""
    result = await db.execute(select(Bot.id).where(Bot.id == bot_id, Bot.user_id == user.id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    engine = StrategyEngine(bot_id, db)
    await engine.initialize()
    return engine


class ManualEntryRequest(BaseModel):
    bot_id: int
    account_balance: float


class ManualCloseRequest(BaseModel):
    bot_id: int


class LimitEntryRequest(BaseModel):
    bot_id: int
    limit_price: float


class CancelLimitRequest(BaseModel):
    bot_id: int


class SignalEntryRequest(BaseModel):
    bot_id: int


@router.post("/entry")
async def manual_entry(
    request: ManualEntryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    engine = await _owned_engine(request.bot_id, db, current_user)
    result = await engine.manual_entry(request.account_balance)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/entry/limit")
async def limit_entry(
    request: LimitEntryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    engine = await _owned_engine(request.bot_id, db, current_user)
    result = await engine.set_limit_entry(request.limit_price)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/entry/signal")
async def signal_entry(
    request: SignalEntryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Переводит бота в ожидание сигнала входа (config.entry_signal)."""
    engine = await _owned_engine(request.bot_id, db, current_user)
    result = await engine.arm_signal_entry()
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/entry/cancel")
async def cancel_limit_entry(
    request: CancelLimitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    engine = await _owned_engine(request.bot_id, db, current_user)
    result = await engine.cancel_limit_entry()
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/close")
async def manual_close(
    request: ManualCloseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    engine = await _owned_engine(request.bot_id, db, current_user)
    result = await engine.manual_close()
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result
