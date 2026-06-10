"""
BTC Dominance Service
Source: CoinGecko API
"""

import aiohttp
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class BTCDominanceService:
    """Service to fetch Bitcoin Dominance from CoinGecko"""

    API_URL = "https://api.coingecko.com/api/v3/global"

    def __init__(self):
        self.cache: Optional[Dict] = None
        self.cache_timestamp: Optional[datetime] = None
        self.cache_ttl = 1800  # 30 minutes
        # Store historical values for 24h change calculation
        self.history: list = []  # [(timestamp, dominance), ...]

    async def fetch(self, use_cache: bool = True) -> Dict:
        """
        Fetch BTC Dominance from CoinCap API

        Returns:
            {
                'dominance': float,
                'change_24h': float,
                'direction': str,
                'market_cap': float,
                'volume_24h': float
            }
        """
        # Check cache
        if use_cache and self.cache and self.cache_timestamp:
            age = (datetime.now(timezone.utc) - self.cache_timestamp).total_seconds()
            if age < self.cache_ttl:
                logger.info(f"Using cached BTC Dominance data (age: {age:.0f}s)")
                return self.cache

        try:
            logger.info("Fetching BTC Dominance from CoinGecko...")

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.API_URL,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status != 200:
                        raise Exception(f"API returned status {response.status}")

                    data = await response.json()

            # Parse response
            if 'data' not in data:
                raise Exception("Invalid API response format")

            global_data = data['data']

            # Get BTC dominance from market_cap_percentage
            btc_dominance = float(global_data['market_cap_percentage'].get('btc', 0))
            current_time = datetime.now(timezone.utc)

            # Add current value to history
            self.history.append((current_time, btc_dominance))

            # Keep only last 48 hours of data (cleanup old entries)
            cutoff_time = current_time - timedelta(hours=48)
            self.history = [(ts, val) for ts, val in self.history if ts > cutoff_time]

            # Calculate 24h change using historical data
            change_24h = 0.0
            value_24h_ago = None

            # Find value closest to 24 hours ago
            target_time = current_time - timedelta(hours=24)
            for ts, val in self.history:
                if ts <= target_time:
                    value_24h_ago = val
                else:
                    break

            if value_24h_ago is not None:
                change_24h = btc_dominance - value_24h_ago
            elif len(self.history) >= 2:
                # Fallback: use oldest available value if we don't have 24h data yet
                value_24h_ago = self.history[0][1]
                change_24h = btc_dominance - value_24h_ago

            # Determine direction
            if change_24h > 0:
                direction = 'up'
            elif change_24h < 0:
                direction = 'down'
            else:
                direction = 'neutral'

            # Get additional data from CoinGecko
            total_market_cap = global_data.get('total_market_cap', {}).get('usd', 0)
            total_volume_24h = global_data.get('total_volume', {}).get('usd', 0)
            active_cryptocurrencies = global_data.get('active_cryptocurrencies', 0)

            result = {
                'dominance': round(btc_dominance, 2),
                'change_24h': round(change_24h, 2),
                'direction': direction,
                'total_market_cap': total_market_cap,
                'total_volume_24h': total_volume_24h,
                'active_cryptocurrencies': active_cryptocurrencies,
                'source': 'coingecko',
                'timestamp': current_time.isoformat()
            }

            # Update cache
            self.cache = result
            self.cache_timestamp = current_time

            logger.info(f"✓ BTC Dominance: {result['dominance']}% ({direction} {abs(change_24h):.2f}%)")

            return result

        except Exception as e:
            logger.error(f"✗ Failed to fetch BTC Dominance: {e}")

            # Return cached data if available
            if self.cache:
                logger.warning("Returning stale cached data")
                return {**self.cache, 'stale': True}

            raise

    def get_interpretation(self, dominance: float, change_24h: float) -> Dict:
        """
        Get interpretation of BTC Dominance

        Args:
            dominance: BTC dominance percentage
            change_24h: 24h change in percentage points

        Returns:
            {
                'trend': str,
                'interpretation': str,
                'altcoin_outlook': str
            }
        """
        # Determine trend
        if dominance > 60:
            trend = 'BTC Season'
            altcoin_outlook = 'Альты под давлением'
        elif dominance > 50:
            trend = 'BTC Dominance'
            altcoin_outlook = 'Нейтрально для альтов'
        elif dominance > 40:
            trend = 'Balanced Market'
            altcoin_outlook = 'Потенциал для альтов'
        else:
            trend = 'Alt Season'
            altcoin_outlook = 'Альты в фаворе'

        # Change interpretation
        if change_24h > 1:
            change_trend = 'Сильный рост BTC.D - давление на альты'
        elif change_24h > 0.3:
            change_trend = 'Рост BTC.D - BTC растет быстрее альтов'
        elif change_24h < -1:
            change_trend = 'Сильное падение BTC.D - альтсезон возможен'
        elif change_24h < -0.3:
            change_trend = 'Падение BTC.D - альты набирают силу'
        else:
            change_trend = 'Стабильная доминация - нейтральная фаза'

        return {
            'trend': trend,
            'change_trend': change_trend,
            'altcoin_outlook': altcoin_outlook,
            'dominance_level': 'high' if dominance > 55 else 'medium' if dominance > 45 else 'low'
        }


# Singleton instance
btc_dominance_service = BTCDominanceService()
