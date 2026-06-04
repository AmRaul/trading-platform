import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.signal_log import SignalLog
from app.ports.market_data import MarketData

logger = logging.getLogger(__name__)

STOP_LOSS_PCT = -4.0  # виртуальный стоп — фиксируем убыток и закрываем сигнал


def _pnl(side: str, entry: float, current: float) -> float:
    if side == "LONG":
        return round((current - entry) / entry * 100, 2)
    else:
        return round((entry - current) / entry * 100, 2)


class UpdateSignalPricesUseCase:
    """Every 5 min — fill in price_15m/30m/60m for PENDING signals."""

    def __init__(self, market_data: MarketData):
        self.market_data = market_data

    async def execute(self, db: AsyncSession) -> None:
        result = await db.execute(
            select(SignalLog).where(SignalLog.status == "PENDING")
        )
        pending = result.scalars().all()
        if not pending:
            return

        now = datetime.now(timezone.utc)

        for row in pending:
            entry_time = row.entry_time
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)

            elapsed = (now - entry_time).total_seconds() / 60  # минуты

            ticker = await self.market_data.get_ticker(row.symbol)
            if not ticker:
                continue
            current_price = float(ticker.get("lastPrice", 0))
            if not current_price:
                continue

            current_pnl = _pnl(row.side, row.entry_price, current_price)

            # Виртуальный стоп-лосс: если цена ушла -4% — фиксируем во все незаполненные точки
            if current_pnl <= STOP_LOSS_PCT:
                if row.price_15m is None:
                    row.price_15m = current_price
                    row.pnl_15m = current_pnl
                if row.price_30m is None:
                    row.price_30m = current_price
                    row.pnl_30m = current_pnl
                if row.price_60m is None:
                    row.price_60m = current_price
                    row.pnl_60m = current_pnl
                row.status = "FILLED"
                logger.info(
                    f"[SIGNAL STOPPED] {row.side} {row.symbol} "
                    f"@ {current_price} pnl={current_pnl:+.2f}% (stop {STOP_LOSS_PCT}%)"
                )
                continue

            if elapsed >= 15 and row.price_15m is None:
                row.price_15m = current_price
                row.pnl_15m = current_pnl

            if elapsed >= 30 and row.price_30m is None:
                row.price_30m = current_price
                row.pnl_30m = current_pnl

            if elapsed >= 60 and row.price_60m is None:
                row.price_60m = current_price
                row.pnl_60m = current_pnl

            # Помечаем FILLED когда все три заполнены
            if row.price_15m is not None and row.price_30m is not None and row.price_60m is not None:
                row.status = "FILLED"
                logger.info(
                    f"[SIGNAL FILLED] {row.side} {row.symbol} "
                    f"pnl15={row.pnl_15m:+.2f}% pnl30={row.pnl_30m:+.2f}% pnl60={row.pnl_60m:+.2f}%"
                )

        await db.commit()
