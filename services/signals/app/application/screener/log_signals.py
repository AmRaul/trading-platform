import logging
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.domain.screener.entities import ScreenerCandidate
from app.domain.screener.signal_detector import SignalDetector
from app.models.signal_log import SignalLog
from app.models.signal_strategy import SignalStrategy

logger = logging.getLogger(__name__)
detector = SignalDetector()


def _matches_custom(candidate: ScreenerCandidate, strategy: SignalStrategy, vol_1h_pct: float) -> bool:
    if strategy.vol_1h_min is not None and vol_1h_pct < strategy.vol_1h_min:
        return False
    if strategy.range_min is not None and (candidate.price_range_pct or 0) < strategy.range_min:
        return False
    if strategy.range_max is not None and (candidate.price_range_pct or 0) > strategy.range_max:
        return False
    if strategy.change_min is not None and candidate.price_change_24h_pct < strategy.change_min:
        return False
    if strategy.change_max is not None and candidate.price_change_24h_pct > strategy.change_max:
        return False
    return True


class LogSignalsUseCase:
    async def execute(self, candidates: List[ScreenerCandidate], db: AsyncSession) -> int:
        if not candidates:
            return 0

        custom_result = await db.execute(
            select(SignalStrategy).where(
                SignalStrategy.is_active == True,
                SignalStrategy.is_builtin == False,
            )
        )
        custom_strategies = custom_result.scalars().all()

        logged = 0
        for c in candidates:
            if not c.volume_24h:
                continue
            vol_1h_pct = (c.volume_1h / c.volume_24h * 100) if c.volume_24h else 0

            # Built-in strategies via SignalDetector
            signals = detector.detect_all(c, vol_1h_pct)
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

            # Custom strategies from DB
            for strategy in custom_strategies:
                if not _matches_custom(c, strategy, vol_1h_pct):
                    continue
                existing = await db.execute(
                    select(SignalLog).where(
                        SignalLog.symbol == c.symbol,
                        SignalLog.strategy == strategy.name,
                        SignalLog.status == "PENDING",
                    )
                )
                if existing.scalar_one_or_none():
                    continue
                side = strategy.side if strategy.side in ("LONG", "SHORT") else "LONG"
                db.add(SignalLog(
                    symbol=c.symbol, side=side, strategy=strategy.name,
                    entry_price=c.last_price, vol_1h_pct=round(vol_1h_pct, 2),
                    price_range_pct=c.price_range_pct or 0,
                    avg_candle_size_pct=c.avg_candle_size_pct,
                    price_change_24h_pct=c.price_change_24h_pct,
                    funding_rate=c.funding_rate, open_interest=c.open_interest,
                    status="PENDING",
                ))
                logged += 1
                logger.info(f"[SIGNAL] {strategy.name} {side} {c.symbol} @ {c.last_price}")

        if logged:
            await db.commit()
        return logged
