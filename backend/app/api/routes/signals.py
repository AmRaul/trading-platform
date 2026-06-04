from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models import User
from app.models.signal_log import SignalLog

router = APIRouter()


@router.get("/")
async def get_signals(
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SignalLog)
        .order_by(desc(SignalLog.entry_time))
        .limit(limit)
    )
    rows = result.scalars().all()

    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "side": r.side,
            "strategy": r.strategy,
            "entry_price": r.entry_price,
            "entry_time": r.entry_time,
            "vol_1h_pct": r.vol_1h_pct,
            "price_range_pct": r.price_range_pct,
            "avg_candle_size_pct": r.avg_candle_size_pct,
            "price_change_24h_pct": r.price_change_24h_pct,
            "funding_rate": r.funding_rate,
            "open_interest": r.open_interest,
            "price_15m": r.price_15m,
            "price_30m": r.price_30m,
            "price_60m": r.price_60m,
            "pnl_15m": r.pnl_15m,
            "pnl_30m": r.pnl_30m,
            "pnl_60m": r.pnl_60m,
            "status": r.status,
        }
        for r in rows
    ]
