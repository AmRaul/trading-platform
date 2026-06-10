"""
Macro Indicators Service
Source: Yahoo Finance
"""

import yfinance as yf
import logging
from datetime import datetime
from typing import Dict, List, Optional
import asyncio

logger = logging.getLogger(__name__)


class MacroService:
    """Service to fetch macro indicators from Yahoo Finance"""

    # Ticker symbols
    SYMBOLS = {
        'DXY': 'DX-Y.NYB',      # US Dollar Index
        'SPX': '^GSPC',          # S&P 500
        'NASDAQ': '^IXIC',       # Nasdaq Composite
        'US10Y': '^TNX',         # 10-Year Treasury Yield
        'GOLD': 'GC=F',          # Gold Futures
        'OIL': 'CL=F',           # Crude Oil Futures (WTI)
        'VIX': '^VIX'            # Volatility Index
    }

    def __init__(self):
        self.cache: Optional[Dict] = None
        self.cache_timestamp: Optional[datetime] = None
        self.cache_ttl = 3600  # 1 hour

    async def fetch(self, use_cache: bool = True) -> Dict:
        """
        Fetch all macro indicators

        Returns:
            {
                'DXY': {'value': float, 'change_daily': float, 'direction': str},
                'SPX': {...},
                ...
            }
        """
        # Check cache
        if use_cache and self.cache and self.cache_timestamp:
            age = (datetime.utcnow() - self.cache_timestamp).total_seconds()
            if age < self.cache_ttl:
                logger.info(f"Using cached Macro data (age: {age:.0f}s)")
                return self.cache

        try:
            logger.info("Fetching Macro indicators from Yahoo Finance...")

            # Run synchronous yfinance calls in executor
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._fetch_sync)

            # Update cache
            self.cache = result
            self.cache_timestamp = datetime.utcnow()

            logger.info(f"✓ Macro data fetched: {len(result)} indicators")

            return result

        except Exception as e:
            logger.error(f"✗ Failed to fetch Macro data: {e}")

            # Return cached data if available
            if self.cache:
                logger.warning("Returning stale cached data")
                return {**self.cache, 'stale': True}

            raise

    def _fetch_sync(self) -> Dict:
        """Synchronous fetch (runs in executor)"""
        results = {}

        for name, ticker_symbol in self.SYMBOLS.items():
            try:
                # Fetch data
                ticker = yf.Ticker(ticker_symbol)
                hist = ticker.history(period='5d')  # Get last 5 days for comparison

                if hist.empty or len(hist) < 2:
                    logger.warning(f"No data for {name} ({ticker_symbol})")
                    continue

                # Get latest and previous values
                current = float(hist['Close'].iloc[-1])
                previous = float(hist['Close'].iloc[-2])

                # Calculate change
                change = ((current - previous) / previous) * 100

                # Determine direction
                if change > 0:
                    direction = 'up'
                elif change < 0:
                    direction = 'down'
                else:
                    direction = 'neutral'

                results[name] = {
                    'value': round(current, 2),
                    'change_daily': round(change, 2),
                    'direction': direction,
                    'previous_close': round(previous, 2),
                    'high_5d': round(float(hist['High'].max()), 2),
                    'low_5d': round(float(hist['Low'].min()), 2),
                    'ticker': ticker_symbol
                }

                logger.debug(f"  {name}: {current:.2f} ({change:+.2f}%)")

            except Exception as e:
                logger.error(f"Failed to fetch {name} ({ticker_symbol}): {e}")
                # Continue with other indicators
                continue

        results['timestamp'] = datetime.utcnow().isoformat()
        results['source'] = 'yahoo_finance'

        return results

    async def fetch_single(self, indicator: str) -> Optional[Dict]:
        """
        Fetch single macro indicator

        Args:
            indicator: One of: DXY, SPX, NASDAQ, US10Y, GOLD, OIL, VIX

        Returns:
            Indicator data or None if failed
        """
        if indicator not in self.SYMBOLS:
            raise ValueError(f"Unknown indicator: {indicator}. Choose from {list(self.SYMBOLS.keys())}")

        try:
            ticker_symbol = self.SYMBOLS[indicator]
            logger.info(f"Fetching {indicator} ({ticker_symbol})...")

            loop = asyncio.get_event_loop()
            ticker = await loop.run_in_executor(None, yf.Ticker, ticker_symbol)
            hist = await loop.run_in_executor(None, lambda: ticker.history(period='5d'))

            if hist.empty or len(hist) < 2:
                raise Exception(f"No data available for {indicator}")

            current = float(hist['Close'].iloc[-1])
            previous = float(hist['Close'].iloc[-2])
            change = ((current - previous) / previous) * 100

            result = {
                'indicator': indicator,
                'value': round(current, 2),
                'change_daily': round(change, 2),
                'direction': 'up' if change > 0 else 'down' if change < 0 else 'neutral',
                'previous_close': round(previous, 2),
                'high_5d': round(float(hist['High'].max()), 2),
                'low_5d': round(float(hist['Low'].min()), 2),
                'timestamp': datetime.utcnow().isoformat(),
                'source': 'yahoo_finance'
            }

            logger.info(f"✓ {indicator}: {result['value']} ({result['change_daily']:+.2f}%)")

            return result

        except Exception as e:
            logger.error(f"✗ Failed to fetch {indicator}: {e}")
            return None

    def get_market_sentiment(self, data: Dict) -> Dict:
        """
        Analyze market sentiment based on macro indicators

        Args:
            data: Macro data from fetch()

        Returns:
            {
                'sentiment': str,
                'risk_appetite': str,
                'interpretation': str
            }
        """
        sentiment_score = 0
        details = []

        # DXY (Dollar Index) - inverse correlation with risk assets
        if 'DXY' in data:
            if data['DXY']['change_daily'] > 0.5:
                sentiment_score -= 1
                details.append("DXY ↑ - давление на риск-активы")
            elif data['DXY']['change_daily'] < -0.5:
                sentiment_score += 1
                details.append("DXY ↓ - позитивно для риск-активов")

        # SPX (S&P 500) - risk appetite indicator
        if 'SPX' in data:
            if data['SPX']['change_daily'] > 0.5:
                sentiment_score += 1
                details.append("SPX ↑ - risk-on")
            elif data['SPX']['change_daily'] < -0.5:
                sentiment_score -= 1
                details.append("SPX ↓ - risk-off")

        # VIX (Volatility) - fear index
        if 'VIX' in data:
            if data['VIX']['value'] > 25:
                sentiment_score -= 1
                details.append("VIX высокий - страх на рынке")
            elif data['VIX']['value'] < 15:
                sentiment_score += 1
                details.append("VIX низкий - комфортность на рынке")

        # GOLD - safe haven indicator
        if 'GOLD' in data:
            if data['GOLD']['change_daily'] > 1:
                sentiment_score -= 0.5
                details.append("GOLD ↑ - поиск безопасности")

        # US10Y - Treasury yields
        if 'US10Y' in data:
            if data['US10Y']['change_daily'] > 5:  # 5% change in yield
                sentiment_score -= 0.5
                details.append("US10Y ↑ - давление на активы")

        # Determine sentiment
        if sentiment_score >= 2:
            sentiment = 'Risk-On'
            risk_appetite = 'High'
            interpretation = 'Сильный аппетит к риску, позитивно для крипты'
        elif sentiment_score >= 1:
            sentiment = 'Bullish'
            risk_appetite = 'Medium-High'
            interpretation = 'Умеренный risk-on, благоприятный фон'
        elif sentiment_score <= -2:
            sentiment = 'Risk-Off'
            risk_appetite = 'Low'
            interpretation = 'Избегание риска, негативно для крипты'
        elif sentiment_score <= -1:
            sentiment = 'Bearish'
            risk_appetite = 'Medium-Low'
            interpretation = 'Осторожность на рынках'
        else:
            sentiment = 'Neutral'
            risk_appetite = 'Medium'
            interpretation = 'Нейтральный макро-фон'

        return {
            'sentiment': sentiment,
            'risk_appetite': risk_appetite,
            'interpretation': interpretation,
            'score': sentiment_score,
            'details': details
        }


# Singleton instance
macro_service = MacroService()
