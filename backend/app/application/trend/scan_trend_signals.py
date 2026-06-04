import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.domain.trend.trend_detector import TrendDetector
from app.models.trend_signal_log import TrendSignalLog
from app.ports.market_data import MarketData

logger = logging.getLogger(__name__)

TREND_SYMBOLS = [
    "SOLUSDT", "AVAXUSDT", "LINKUSDT",
    "ETHUSDT", "BNBUSDT", "DOTUSDT", "AAVEUSDT",
]

detector = TrendDetector()


class ScanTrendSignalsUseCase:
    def __init__(self, market_data: MarketData):
        self.market_data = market_data

    async def execute(self, db: AsyncSession) -> int:
        logged = 0
        semaphore = asyncio.Semaphore(3)

        async def scan_one(symbol: str) -> None:
            nonlocal logged
            async with semaphore:
                try:
                    candles_4h  = await self.market_data.get_klines(symbol, "240", 50)
                    candles_1h  = await self.market_data.get_klines(symbol, "60", 50)
                    candles_15m = await self.market_data.get_klines(symbol, "15", 10)

                    if not candles_4h or not candles_1h or not candles_15m:
                        return

                    signal = detector.detect(symbol, candles_4h, candles_1h, candles_15m)
                    if not signal:
                        return

                    # Не дублировать — пропустить если уже есть OPEN сигнал по символу+side
                    existing = await db.execute(
                        select(TrendSignalLog).where(
                            TrendSignalLog.symbol == signal.symbol,
                            TrendSignalLog.side == signal.side,
                            TrendSignalLog.status == "OPEN",
                        )
                    )
                    if existing.scalar_one_or_none():
                        return

                    row = TrendSignalLog(
                        symbol=signal.symbol,
                        side=signal.side,
                        entry_price=signal.entry_price,
                        ema21_4h=signal.ema21_4h,
                        ema21_1h=signal.ema21_1h,
                        trend_4h=signal.trend_4h,
                        pullback_1h=signal.pullback_1h,
                        trigger_15m=signal.trigger_15m,
                        stop_price=signal.stop_price,
                        stop_pct=signal.stop_pct,
                        status="OPEN",
                    )
                    db.add(row)
                    logged += 1
                    logger.info(
                        f"[TREND] {signal.side} {symbol} @ {signal.entry_price} "
                        f"stop={signal.stop_price} ({signal.stop_pct:.1f}%) "
                        f"EMA4H={signal.ema21_4h:.4f} trend={signal.trend_4h}"
                    )
                except Exception as e:
                    logger.error(f"[TREND] Error scanning {symbol}: {e}")

        await asyncio.gather(*[scan_one(s) for s in TREND_SYMBOLS])

        if logged:
            await db.commit()
            logger.info(f"[TREND] Logged {logged} new trend signals")

        return logged
