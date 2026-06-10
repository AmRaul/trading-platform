"""
Fear & Greed Index Service
Source: Alternative.me API
"""

import aiohttp
import logging
from datetime import datetime
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class FearGreedService:
    """Service to fetch Fear & Greed Index from Alternative.me"""

    API_URL = "https://api.alternative.me/fng/"

    def __init__(self):
        self.cache: Optional[Dict] = None
        self.cache_timestamp: Optional[datetime] = None
        self.cache_ttl = 3600  # 1 hour

    async def fetch(self, use_cache: bool = True) -> Dict:
        """
        Fetch Fear & Greed Index

        Returns:
            {
                'value': int (0-100),
                'value_classification': str,
                'timestamp': str (ISO format),
                'time_until_update': str
            }
        """
        # Check cache
        if use_cache and self.cache and self.cache_timestamp:
            age = (datetime.utcnow() - self.cache_timestamp).total_seconds()
            if age < self.cache_ttl:
                logger.info(f"Using cached Fear & Greed data (age: {age:.0f}s)")
                return self.cache

        try:
            logger.info("Fetching Fear & Greed Index from Alternative.me...")

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.API_URL,
                    params={'limit': 1},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status != 200:
                        raise Exception(f"API returned status {response.status}")

                    data = await response.json()

            # Parse response
            if 'data' not in data or not data['data']:
                raise Exception("Invalid API response format")

            latest = data['data'][0]

            result = {
                'value': int(latest['value']),
                'value_classification': latest['value_classification'],
                'timestamp': datetime.fromtimestamp(int(latest['timestamp'])).isoformat(),
                'time_until_update': latest.get('time_until_update'),
                'source': 'alternative.me',
                'fetched_at': datetime.utcnow().isoformat()
            }

            # Update cache
            self.cache = result
            self.cache_timestamp = datetime.utcnow()

            logger.info(f"✓ Fear & Greed: {result['value']} ({result['value_classification']})")

            return result

        except Exception as e:
            logger.error(f"✗ Failed to fetch Fear & Greed: {e}")

            # Return cached data if available
            if self.cache:
                logger.warning("Returning stale cached data")
                return {**self.cache, 'stale': True}

            raise

    async def fetch_history(self, days: int = 30) -> Dict:
        """
        Fetch historical Fear & Greed data

        Args:
            days: Number of days to fetch (max 365)

        Returns:
            List of historical data points
        """
        try:
            logger.info(f"Fetching {days} days of Fear & Greed history...")

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.API_URL,
                    params={'limit': days},
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status != 200:
                        raise Exception(f"API returned status {response.status}")

                    data = await response.json()

            if 'data' not in data:
                raise Exception("Invalid API response format")

            history = []
            for entry in data['data']:
                history.append({
                    'value': int(entry['value']),
                    'value_classification': entry['value_classification'],
                    'timestamp': datetime.fromtimestamp(int(entry['timestamp'])).isoformat()
                })

            logger.info(f"✓ Fetched {len(history)} historical data points")

            return {
                'data': history,
                'count': len(history),
                'fetched_at': datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"✗ Failed to fetch Fear & Greed history: {e}")
            raise

    def get_interpretation(self, value: int) -> Dict:
        """
        Get interpretation of Fear & Greed value

        Args:
            value: Fear & Greed value (0-100)

        Returns:
            {
                'zone': str,
                'emoji': str,
                'advice': str,
                'color': str
            }
        """
        if value <= 25:
            return {
                'zone': 'Extreme Fear',
                'emoji': '😨',
                'advice': 'Возможность для покупки - рынок в панике',
                'color': 'green',
                'action': 'BUY'
            }
        elif value <= 45:
            return {
                'zone': 'Fear',
                'emoji': '😰',
                'advice': 'Осторожный оптимизм - хорошее время для входа',
                'color': 'lightgreen',
                'action': 'ACCUMULATE'
            }
        elif value <= 55:
            return {
                'zone': 'Neutral',
                'emoji': '😐',
                'advice': 'Рынок в равновесии - ожидайте сигналов',
                'color': 'gray',
                'action': 'HOLD'
            }
        elif value <= 75:
            return {
                'zone': 'Greed',
                'emoji': '😊',
                'advice': 'Будьте осторожны - возможна коррекция',
                'color': 'orange',
                'action': 'CAREFUL'
            }
        else:
            return {
                'zone': 'Extreme Greed',
                'emoji': '🤑',
                'advice': 'Риск коррекции высок - фиксируйте прибыль',
                'color': 'red',
                'action': 'SELL'
            }


# Singleton instance
fear_greed_service = FearGreedService()
