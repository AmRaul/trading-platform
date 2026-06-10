"""
Market Narrative Analyzer
Aggregates multiple signals to determine overall market state
"""

import logging
from datetime import datetime
from typing import Dict, Optional
import ccxt

from .fear_greed import fear_greed_service
from .btc_dominance import btc_dominance_service
from .macro import macro_service

logger = logging.getLogger(__name__)


class NarrativeAnalyzer:
    """
    Analyzes market narrative based on multiple signals:
    - Price Action (BTC trend vs moving averages)
    - Funding Rates (futures sentiment)
    - Open Interest (leverage in market)
    - Fear & Greed Index
    - BTC Dominance
    - Macro Environment
    """

    def __init__(self):
        self.exchange = None

    def _get_exchange(self):
        """Get exchange instance"""
        if self.exchange is None:
            self.exchange = ccxt.binance({
                'enableRateLimit': True,
                'options': {'defaultType': 'future'}
            })
        return self.exchange

    async def analyze(self) -> Dict:
        """
        Analyze market narrative

        Returns:
            {
                'narrative': str,  # Risk-on, Risk-off, Distribution, Accumulation, Uncertain
                'confidence': float,  # 0.0 - 1.0
                'score': int,  # -100 to +100
                'components': dict,
                'interpretation': str
            }
        """
        try:
            logger.info("Analyzing market narrative...")

            # Fetch all components
            fear_greed = await fear_greed_service.fetch()
            btc_dom = await btc_dominance_service.fetch()
            macro = await macro_service.fetch()

            # Analyze each component
            score = 0
            components = {}
            confidence_factors = []

            # 1. Price Action (30% weight)
            price_score, price_component = await self._analyze_price_action()
            score += price_score
            components['price_action'] = price_component
            confidence_factors.append(abs(price_score) / 30)

            # 2. Fear & Greed (25% weight)
            fg_score, fg_component = self._analyze_fear_greed(fear_greed)
            score += fg_score
            components['sentiment'] = fg_component
            confidence_factors.append(abs(fg_score) / 25)

            # 3. BTC Dominance (20% weight)
            dom_score, dom_component = self._analyze_btc_dominance(btc_dom)
            score += dom_score
            components['btc_dominance'] = dom_component
            confidence_factors.append(abs(dom_score) / 20)

            # 4. Funding Rates (15% weight)
            funding_score, funding_component = await self._analyze_funding()
            score += funding_score
            components['funding'] = funding_component
            confidence_factors.append(abs(funding_score) / 15)

            # 5. Macro Environment (10% weight)
            macro_score, macro_component = self._analyze_macro(macro)
            score += macro_score
            components['macro'] = macro_component
            confidence_factors.append(abs(macro_score) / 10)

            # Calculate overall narrative
            narrative = self._calculate_narrative(score)

            # Calculate confidence (0.0 - 1.0)
            confidence = sum(confidence_factors) / len(confidence_factors) if confidence_factors else 0.5

            result = {
                'narrative': narrative,
                'confidence': round(min(confidence, 1.0), 2),
                'score': score,
                'components': components,
                'interpretation': self._get_interpretation(narrative, score),
                'timestamp': datetime.utcnow().isoformat()
            }

            logger.info(f"✓ Narrative: {narrative} (score: {score}, confidence: {confidence:.2f})")

            return result

        except Exception as e:
            logger.error(f"✗ Failed to analyze narrative: {e}")
            return {
                'narrative': 'Uncertain',
                'confidence': 0.0,
                'score': 0,
                'components': {},
                'interpretation': 'Недостаточно данных для анализа',
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }

    async def _analyze_price_action(self) -> tuple:
        """Analyze BTC price action vs moving averages"""
        try:
            import asyncio

            def _fetch_price_data():
                exchange = self._get_exchange()
                return exchange.fetch_ohlcv('BTC/USDT', '1h', limit=200)

            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            ohlcv = await loop.run_in_executor(None, _fetch_price_data)

            if len(ohlcv) < 200:
                return 0, 'insufficient_data'

            closes = [candle[4] for candle in ohlcv]
            current_price = closes[-1]

            # Calculate MAs
            ma_50 = sum(closes[-50:]) / 50
            ma_200 = sum(closes[-200:]) / 200

            score = 0
            if current_price > ma_200:
                score += 15  # Above 200 MA - bullish
                if current_price > ma_50:
                    score += 15  # Above both - strong bull
                    component = 'strong_bullish'
                else:
                    component = 'bullish'
            elif current_price < ma_200:
                score -= 15  # Below 200 MA - bearish
                if current_price < ma_50:
                    score -= 15  # Below both - strong bear
                    component = 'strong_bearish'
                else:
                    component = 'bearish'
            else:
                component = 'neutral'

            logger.debug(f"Price Action: {component} (score: {score})")
            return score, component

        except Exception as e:
            logger.error(f"Error analyzing price action: {e}")
            return 0, 'error'

    def _analyze_fear_greed(self, data: Dict) -> tuple:
        """Analyze Fear & Greed Index"""
        value = data.get('value', 50)

        if value < 25:  # Extreme Fear
            score = 25  # Contrarian - buy opportunity
            component = 'extreme_fear_buy'
        elif value < 45:  # Fear
            score = 15
            component = 'fear_cautious'
        elif value < 55:  # Neutral
            score = 0
            component = 'neutral'
        elif value < 75:  # Greed
            score = -15  # Caution
            component = 'greed_caution'
        else:  # Extreme Greed
            score = -25  # High risk
            component = 'extreme_greed_risk'

        logger.debug(f"Fear & Greed: {component} (score: {score})")
        return score, component

    def _analyze_btc_dominance(self, data: Dict) -> tuple:
        """Analyze BTC Dominance trend"""
        dominance = data.get('dominance', 50)
        change = data.get('change_24h', 0)

        score = 0

        # Dominance level
        if dominance > 60:
            score -= 10  # High dom - risk-off usually
        elif dominance < 40:
            score += 10  # Low dom - alt-friendly, risk-on

        # Dominance change
        if change > 1:
            score -= 10  # Rising dom - BTC season, risk-off
            component = 'rising_btc_season'
        elif change < -1:
            score += 10  # Falling dom - alt season, risk-on
            component = 'falling_alt_season'
        else:
            component = 'stable'

        logger.debug(f"BTC Dominance: {component} (score: {score})")
        return score, component

    async def _analyze_funding(self) -> tuple:
        """Analyze BTC funding rate"""
        try:
            import asyncio

            def _fetch_funding():
                exchange = self._get_exchange()
                return exchange.fetch_funding_rate('BTC/USDT:USDT')

            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            funding_rate = await loop.run_in_executor(None, _fetch_funding)
            rate = funding_rate.get('fundingRate', 0) * 100  # Convert to percentage

            if rate > 0.03:  # Very positive - overheated
                score = -15
                component = 'overheated'
            elif rate > 0.01:  # Positive - bullish but careful
                score = -5
                component = 'positive'
            elif rate < -0.03:  # Very negative - capitulation
                score = 15
                component = 'capitulation'
            elif rate < -0.01:  # Negative - fear
                score = 5
                component = 'negative'
            else:  # Neutral
                score = 0
                component = 'neutral'

            logger.debug(f"Funding Rate: {rate:.4f}% - {component} (score: {score})")
            return score, component

        except Exception as e:
            logger.error(f"Error analyzing funding: {e}")
            return 0, 'error'

    def _analyze_macro(self, data: Dict) -> tuple:
        """Analyze macro environment"""
        if 'stale' in data or not data:
            return 0, 'no_data'

        score = 0

        # DXY (inverse)
        if 'DXY' in data:
            if data['DXY']['change_daily'] > 0.5:
                score -= 5
            elif data['DXY']['change_daily'] < -0.5:
                score += 5

        # SPX (direct)
        if 'SPX' in data:
            if data['SPX']['change_daily'] > 0.5:
                score += 5
            elif data['SPX']['change_daily'] < -0.5:
                score -= 5

        if score > 5:
            component = 'risk_on'
        elif score < -5:
            component = 'risk_off'
        else:
            component = 'neutral'

        logger.debug(f"Macro: {component} (score: {score})")
        return score, component

    def _calculate_narrative(self, score: int) -> str:
        """Calculate narrative from total score"""
        if score > 40:
            return 'Risk-on'
        elif score > 15:
            return 'Accumulation'
        elif score < -40:
            return 'Risk-off'
        elif score < -15:
            return 'Distribution'
        else:
            return 'Uncertain'

    def _get_interpretation(self, narrative: str, score: int) -> str:
        """Get human-readable interpretation"""
        interpretations = {
            'Risk-on': 'Рынок в режиме роста, высокий аппетит к риску. Благоприятные условия для крипты.',
            'Accumulation': 'Фаза накопления. Умные деньги заходят. Хорошее время для позиций.',
            'Risk-off': 'Рынок избегает риска. Высокая вероятность распродаж. Будьте осторожны.',
            'Distribution': 'Фаза распределения. Крупные игроки фиксируют прибыль. Риск коррекции.',
            'Uncertain': 'Неопределенность на рынке. Ждем более четких сигналов.'
        }
        return interpretations.get(narrative, 'Нет интерпретации')


# Singleton instance
narrative_analyzer = NarrativeAnalyzer()
