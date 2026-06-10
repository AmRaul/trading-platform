"""
Altseason Index Service
Simple calculation based on top altcoins vs BTC performance
"""

import ccxt
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
import asyncio

logger = logging.getLogger(__name__)


class AltseasonService:
    """Service to calculate Altseason Index"""

    # Top altcoins to compare (excluding stablecoins) - simplified to top 5
    TOP_ALTS = [
        'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT'
    ]

    def __init__(self):
        self.cache: Optional[Dict] = None
        self.cache_timestamp: Optional[datetime] = None
        self.cache_ttl = 3600  # 1 hour
        self.exchange = None

    def _get_exchange(self):
        """Get exchange instance"""
        if self.exchange is None:
            self.exchange = ccxt.binance({
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'}
            })
        return self.exchange

    async def fetch(self, use_cache: bool = True) -> Dict:
        """
        Calculate Altseason Index

        Returns:
            {
                'index': int (0-100),
                'phase': str (BTC Season / Neutral / Altseason),
                'alts_outperforming': int,
                'total_alts': int
            }
        """
        # Check cache
        if use_cache and self.cache and self.cache_timestamp:
            age = (datetime.now(timezone.utc) - self.cache_timestamp).total_seconds()
            if age < self.cache_ttl:
                logger.info(f"Using cached Altseason data (age: {age:.0f}s)")
                return self.cache

        try:
            logger.info("Calculating Altseason Index...")

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._calculate_index)

            # Update cache
            self.cache = result
            self.cache_timestamp = datetime.now(timezone.utc)

            logger.info(f"✓ Altseason Index: {result['index']} ({result['phase']})")

            return result

        except Exception as e:
            logger.error(f"✗ Failed to calculate Altseason Index: {e}")

            # Return cached data if available
            if self.cache:
                logger.warning("Returning stale cached data")
                return {**self.cache, 'stale': True}

            # Return default values
            return {
                'index': 50,
                'phase': 'Neutral',
                'alts_outperforming': 0,
                'total_alts': len(self.TOP_ALTS),
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

    def _calculate_index(self) -> Dict:
        """Synchronous calculation (runs in executor)"""
        exchange = self._get_exchange()

        # Get 30-day performance for BTC and altcoins (simplified from 90 days)
        days = 30
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=days)

        try:
            # Get BTC performance
            btc_ohlcv = exchange.fetch_ohlcv(
                'BTC/USDT',
                timeframe='1d',
                since=int(start_time.timestamp() * 1000),
                limit=days
            )

            if len(btc_ohlcv) < 2:
                raise Exception("Not enough BTC data")

            btc_start = btc_ohlcv[0][4]  # Close price at start
            btc_end = btc_ohlcv[-1][4]   # Close price at end
            btc_performance = ((btc_end - btc_start) / btc_start) * 100

            logger.debug(f"BTC {days}d performance: {btc_performance:+.2f}%")

            # Count how many altcoins outperformed BTC
            alts_outperforming = 0
            successful_alts = 0
            alt_performances = []

            for symbol in self.TOP_ALTS:
                try:
                    alt_ohlcv = exchange.fetch_ohlcv(
                        symbol,
                        timeframe='1d',
                        since=int(start_time.timestamp() * 1000),
                        limit=days
                    )

                    if len(alt_ohlcv) < 2:
                        continue

                    alt_start = alt_ohlcv[0][4]
                    alt_end = alt_ohlcv[-1][4]
                    alt_performance = ((alt_end - alt_start) / alt_start) * 100

                    alt_performances.append({
                        'symbol': symbol,
                        'performance': alt_performance
                    })

                    successful_alts += 1

                    if alt_performance > btc_performance:
                        alts_outperforming += 1

                    logger.debug(f"  {symbol}: {alt_performance:+.2f}% (vs BTC: {btc_performance:+.2f}%)")

                except Exception as e:
                    logger.warning(f"Failed to fetch {symbol}: {e}")
                    continue

            # Calculate index (0-100)
            if successful_alts > 0:
                index = int((alts_outperforming / successful_alts) * 100)
            else:
                index = 50  # Neutral if no data

            # Determine phase
            if index >= 75:
                phase = 'Altseason'
            elif index >= 60:
                phase = 'Alt-Friendly'
            elif index <= 25:
                phase = 'BTC Season'
            elif index <= 40:
                phase = 'BTC-Friendly'
            else:
                phase = 'Neutral'

            result = {
                'index': index,
                'phase': phase,
                'alts_outperforming': alts_outperforming,
                'total_alts': successful_alts,
                'btc_performance': round(btc_performance, 2),
                'days': days,
                'top_performers': sorted(alt_performances, key=lambda x: x['performance'], reverse=True)[:3],
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'source': 'calculated'
            }

            return result

        except Exception as e:
            logger.error(f"Error calculating Altseason Index: {e}")
            raise

    def get_interpretation(self, index: int) -> Dict:
        """
        Get interpretation of Altseason Index

        Args:
            index: Altseason index (0-100)

        Returns:
            {
                'phase': str,
                'advice': str,
                'emoji': str
            }
        """
        if index >= 75:
            return {
                'phase': 'Altseason',
                'advice': 'Альты сильно обгоняют BTC - отличное время для альткоинов',
                'emoji': '🚀',
                'action': 'ALTS'
            }
        elif index >= 60:
            return {
                'phase': 'Alt-Friendly',
                'advice': 'Альты показывают хорошие результаты - можно присмотреться к альтам',
                'emoji': '📈',
                'action': 'MIXED'
            }
        elif index >= 40:
            return {
                'phase': 'Neutral',
                'advice': 'Сбалансированный рынок - BTC и альты примерно равны',
                'emoji': '⚖️',
                'action': 'BALANCED'
            }
        elif index >= 25:
            return {
                'phase': 'BTC-Friendly',
                'advice': 'BTC опережает альты - фокус на Bitcoin',
                'emoji': '₿',
                'action': 'BTC_FOCUS'
            }
        else:
            return {
                'phase': 'BTC Season',
                'advice': 'Сильный BTC season - избегайте альткоинов',
                'emoji': '🟠',
                'action': 'BTC'
            }


# Singleton instance
altseason_service = AltseasonService()
