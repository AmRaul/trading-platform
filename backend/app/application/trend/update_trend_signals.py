import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.domain.trend.ema_calculator import ema21_series
from app.models.trend_signal_log import TrendSignalLog
from app.ports.market_data import MarketData

logger = logging.getLogger(__name__)


def _elapsed_hours(entry_time: datetime) -> float:
    if entry_time.tzinfo is None:
        entry_time = entry_time.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - entry_time
    return round(delta.total_seconds() / 3600, 2)


class UpdateTrendSignalsUseCase:
    def __init__(self, market_data: MarketData):
        self.market_data = market_data

    async def execute(self, db: AsyncSession) -> None:
        result = await db.execute(
            select(TrendSignalLog).where(TrendSignalLog.status == "OPEN")
        )
        open_signals = result.scalars().all()
        if not open_signals:
            return

        for row in open_signals:
            try:
                ticker = await self.market_data.get_ticker(row.symbol)
                if not ticker:
                    continue
                current = float(ticker.get("lastPrice", 0))
                if not current:
                    continue

                if row.side == "LONG":
                    pnl = (current - row.entry_price) / row.entry_price * 100
                else:
                    pnl = (row.entry_price - current) / row.entry_price * 100

                # Обновить peak_pnl
                if pnl > (row.peak_pnl_pct or 0):
                    row.peak_pnl_pct = round(pnl, 2)

                # Проверка стопа
                stop_hit = (
                    (row.side == "LONG" and current <= row.stop_price) or
                    (row.side == "SHORT" and current >= row.stop_price)
                )
                if stop_hit:
                    row.exit_price = current
                    row.exit_time = datetime.now(timezone.utc)
                    row.exit_reason = "STOP"
                    row.pnl_pct = round(pnl, 2)
                    row.duration_hrs = _elapsed_hours(row.entry_time)
                    row.status = "CLOSED"
                    logger.info(
                        f"[TREND STOP] {row.side} {row.symbol} "
                        f"entry={row.entry_price} exit={current} pnl={pnl:+.2f}% "
                        f"duration={row.duration_hrs}h"
                    )
                    continue

                # Проверка EMA выхода (1H close < EMA21 для LONG, > для SHORT)
                candles_1h = await self.market_data.get_klines(row.symbol, "60", 30)
                if candles_1h and len(candles_1h) >= 22:
                    closes_1h = [float(c["close"]) for c in candles_1h]
                    ema_series = ema21_series(closes_1h)
                    if ema_series:
                        ema_now = ema_series[-1]
                        last_1h_close = closes_1h[-1]
                        ema_exit = (
                            (row.side == "LONG" and last_1h_close < ema_now) or
                            (row.side == "SHORT" and last_1h_close > ema_now)
                        )
                        if ema_exit:
                            row.exit_price = current
                            row.exit_time = datetime.now(timezone.utc)
                            row.exit_reason = "EMA_EXIT"
                            row.pnl_pct = round(pnl, 2)
                            row.duration_hrs = _elapsed_hours(row.entry_time)
                            row.status = "CLOSED"
                            logger.info(
                                f"[TREND EMA_EXIT] {row.side} {row.symbol} "
                                f"1H_close={last_1h_close:.4f} < EMA21={ema_now:.4f} "
                                f"pnl={pnl:+.2f}% duration={row.duration_hrs}h"
                            )

            except Exception as e:
                logger.error(f"[TREND] Error updating {row.symbol}: {e}")

        await db.commit()
