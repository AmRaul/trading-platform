import asyncio
import logging
from datetime import datetime
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.screener.entities import ScreenerCandidate
from app.domain.screener.volatility_analyzer import VolatilityAnalyzer
from app.models.screener_snapshot import ScreenerSnapshot
from app.ports.market_data import MarketData

logger = logging.getLogger(__name__)

TOP_N = 50          # сколько монет сканировать
CANDLES_LIMIT = 35  # достаточно для ATR(14) + CANDLE_WINDOW(20) + запас


class ScanMarketUseCase:
    def __init__(self, market_data: MarketData):
        self.market_data = market_data
        self.analyzer = VolatilityAnalyzer()

    async def execute(self, db: AsyncSession) -> List[ScreenerCandidate]:
        """Scan top-N futures by volume, return volatile candidates and save to DB."""
        tickers = await self._get_top_tickers()
        if not tickers:
            logger.warning("Screener: no tickers received from Bybit")
            return []

        logger.info(f"Screener: scanning {len(tickers)} symbols...")

        candidates = []
        # Limit concurrency to avoid hammering the API
        semaphore = asyncio.Semaphore(5)

        async def scan_one(ticker: dict) -> None:
            async with semaphore:
                try:
                    result = await self._scan_symbol(ticker)
                    if result:
                        candidates.append(result)
                except Exception as e:
                    logger.error(f"Screener error for {ticker.get('symbol')}: {e}")

        await asyncio.gather(*[scan_one(t) for t in tickers])

        # Sort by volatility descending
        candidates.sort(key=lambda c: c.avg_candle_size_pct, reverse=True)

        await self._save(candidates, db)
        logger.info(f"Screener: found {len(candidates)} volatile symbols")

        from app.application.screener.log_signals import LogSignalsUseCase
        logged = await LogSignalsUseCase().execute(candidates, db)
        if logged:
            logger.info(f"Screener: logged {logged} entry signals")

        return candidates

    async def _get_top_tickers(self) -> list:
        """Fetch all linear futures tickers, return top-N by 24h turnover."""
        try:
            from app.services.bybit import bybit_client
            response = bybit_client.http_client.get_tickers(category="linear")
            if response["retCode"] != 0:
                return []

            tickers = response["result"]["list"]
            # Filter out inverse/perp noise — keep USDT pairs only
            tickers = [t for t in tickers if t["symbol"].endswith("USDT")]
            # Sort by 24h turnover (in USDT) descending
            tickers.sort(key=lambda t: float(t.get("turnover24h", 0)), reverse=True)
            return tickers[:TOP_N]
        except Exception as e:
            logger.error(f"Screener: failed to get tickers: {e}")
            return []

    async def _scan_symbol(self, ticker: dict) -> ScreenerCandidate | None:
        symbol = ticker["symbol"]
        candles_1m, candles_1h = await asyncio.gather(
            self.market_data.get_klines(symbol, "1", CANDLES_LIMIT),
            self.market_data.get_klines(symbol, "60", 2),
        )
        if not candles_1m:
            return None

        funding_rate = float(ticker.get("fundingRate", 0))
        return self.analyzer.analyze(symbol, candles_1m, ticker, funding_rate, candles_1h)

    async def _save(self, candidates: List[ScreenerCandidate], db: AsyncSession) -> None:
        if not candidates:
            return
        batch_time = candidates[0].scanned_at  # единый timestamp для всего батча
        for c in candidates:
            snapshot = ScreenerSnapshot(
                symbol=c.symbol,
                scanned_at=batch_time,
                avg_candle_size_pct=c.avg_candle_size_pct,
                atr=c.atr,
                volume_24h=c.volume_24h,
                volume_7d_avg=c.volume_7d_avg,
                volume_ratio=c.volume_ratio,
                volume_1h=c.volume_1h,
                funding_rate=c.funding_rate,
                price_change_24h_pct=c.price_change_24h_pct,
                high_24h=c.high_24h,
                low_24h=c.low_24h,
                open_interest=c.open_interest,
                direction=c.direction,
                price_range_pct=c.price_range_pct,
                last_price=c.last_price,
            )
            db.add(snapshot)
        await db.commit()
        logger.info(f"Screener: saved {len(candidates)} snapshots to DB")
