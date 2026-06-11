import logging
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.domain.screener.entities import ScreenerCandidate
from app.domain.screener.signal_detector import SignalDetector
from app.models.signal_log import SignalLog

logger = logging.getLogger(__name__)
detector = SignalDetector()


class LogSignalsUseCase:
    async def execute(self, candidates: List[ScreenerCandidate], db: AsyncSession) -> int:
        if not candidates:
            return 0
        logged = 0
        for c in candidates:
            if not c.volume_24h:
                continue
            vol_1h_pct = (c.volume_1h / c.volume_24h * 100) if c.volume_24h else 0
            signals = detector.detect_all(c, vol_1h_pct)
            if not signals:
                continue
            for signal in signals:
                existing = await db.execute(
                    select(SignalLog).where(
                        SignalLog.symbol == signal.symbol,
                        SignalLog.strategy == signal.strategy,
                        SignalLog.status == "PENDING",
                    )
                )
                if existing.scalar_one_or_none():
                    continue
                db.add(SignalLog(
                    symbol=signal.symbol, side=signal.side, strategy=signal.strategy,
                    entry_price=signal.entry_price, vol_1h_pct=signal.vol_1h_pct,
                    price_range_pct=signal.price_range_pct,
                    avg_candle_size_pct=signal.avg_candle_size_pct,
                    price_change_24h_pct=signal.price_change_24h_pct,
                    funding_rate=signal.funding_rate, open_interest=signal.open_interest,
                    status="PENDING",
                ))
                logged += 1
                logger.info(f"[SIGNAL] {signal.strategy} {signal.side} {signal.symbol} @ {signal.entry_price}")
        if logged:
            await db.commit()
        return logged
