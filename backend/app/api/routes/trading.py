from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.database import get_db
from app.models import User
from app.services.strategy import StrategyEngine
from app.api.deps import get_current_user

router = APIRouter()


class ManualEntryRequest(BaseModel):
    bot_id: int
    account_balance: float


class ManualCloseRequest(BaseModel):
    bot_id: int


@router.post("/entry")
async def manual_entry(
    request: ManualEntryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Manually trigger entry for a bot"""
    engine = StrategyEngine(request.bot_id, db)
    await engine.initialize()

    result = await engine.manual_entry(request.account_balance)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result


@router.post("/close")
async def manual_close(
    request: ManualCloseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Manually close position for a bot"""
    engine = StrategyEngine(request.bot_id, db)
    await engine.initialize()

    result = await engine.manual_close()

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result
