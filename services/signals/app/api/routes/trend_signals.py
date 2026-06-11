from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.database import get_db
from app.models.trend_signal_log import TrendSignalLog

router = APIRouter()


@router.get("/")
async def get_trend_signals(limit: int = 200, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TrendSignalLog).order_by(desc(TrendSignalLog.entry_time)).limit(limit)
    )
    rows = result.scalars().all()
    return [
        {
            "id": r.id, "symbol": r.symbol, "side": r.side,
            "entry_price": r.entry_price, "entry_time": r.entry_time,
            "ema21_4h": r.ema21_4h, "ema21_1h": r.ema21_1h,
            "trend_4h": r.trend_4h, "pullback_1h": r.pullback_1h,
            "trigger_15m": r.trigger_15m, "stop_price": r.stop_price,
            "stop_pct": r.stop_pct, "exit_price": r.exit_price,
            "exit_time": r.exit_time, "exit_reason": r.exit_reason,
            "pnl_pct": r.pnl_pct, "duration_hrs": r.duration_hrs,
            "peak_pnl_pct": r.peak_pnl_pct, "pyramid_count": r.pyramid_count,
            "status": r.status,
        }
        for r in rows
    ]
