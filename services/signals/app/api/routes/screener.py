from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from datetime import datetime

from app.core.database import get_db
from app.models.screener_snapshot import ScreenerSnapshot
from app.application.screener.scan_market import ScanMarketUseCase
from app.adapters.bybit_market_data import BybitMarketDataAdapter

router = APIRouter()


def _snapshot_dict(s):
    return {
        "symbol": s.symbol, "avg_candle_size_pct": s.avg_candle_size_pct,
        "atr": s.atr, "volume_24h": s.volume_24h, "volume_1h": s.volume_1h,
        "volume_ratio": s.volume_ratio, "funding_rate": s.funding_rate,
        "price_change_24h_pct": s.price_change_24h_pct, "high_24h": s.high_24h,
        "low_24h": s.low_24h, "open_interest": s.open_interest,
        "direction": s.direction, "price_range_pct": s.price_range_pct,
        "last_price": s.last_price,
    }


@router.get("/latest")
async def get_latest_scan(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(func.max(ScreenerSnapshot.scanned_at)))
    latest_time = result.scalar_one_or_none()
    if not latest_time:
        return {"scanned_at": None, "candidates": []}
    result = await db.execute(
        select(ScreenerSnapshot)
        .where(ScreenerSnapshot.scanned_at == latest_time)
        .order_by(desc(ScreenerSnapshot.avg_candle_size_pct))
    )
    snapshots = result.scalars().all()
    return {"scanned_at": latest_time, "count": len(snapshots),
            "candidates": [_snapshot_dict(s) for s in snapshots]}


@router.post("/scan")
async def trigger_scan(db: AsyncSession = Depends(get_db)):
    use_case = ScanMarketUseCase(BybitMarketDataAdapter())
    candidates = await use_case.execute(db)
    return {"scanned_at": datetime.utcnow(), "count": len(candidates),
            "candidates": [_snapshot_dict(c) for c in candidates]}
