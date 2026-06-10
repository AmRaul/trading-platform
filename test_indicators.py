"""
Минимальные тесты для модуля indicators.py
Проверяет базовую работоспособность модуля
"""

import pytest
import pandas as pd
import numpy as np
from indicators import TechnicalIndicators, IndicatorStrategy


@pytest.fixture
def sample_data():
    """Создает образец данных OHLCV для тестирования"""
    dates = pd.date_range('2023-01-01', periods=300, freq='15min')
    np.random.seed(42)
    base_price = 30000
    prices = base_price + np.cumsum(np.random.randn(300) * 100)
    
    return pd.DataFrame({
        'open': prices + np.random.randn(300) * 50,
        'high': prices + np.abs(np.random.randn(300) * 100),
        'low': prices - np.abs(np.random.randn(300) * 100),
        'close': prices,
        'volume': np.random.randint(1000, 10000, 300)
    }, index=dates)


class TestTechnicalIndicators:
    """Минимальные тесты для TechnicalIndicators"""
    
    def test_import_and_instantiation(self):
        """Проверка импорта и создания экземпляра"""
        indicators = TechnicalIndicators()
        assert indicators is not None
    
    def test_ema_calculation(self, sample_data):
        """Проверка расчета EMA"""
        indicators = TechnicalIndicators()
        ema = indicators.calculate_ema(sample_data['close'], period=50)
        assert isinstance(ema, pd.Series)
        assert len(ema) == len(sample_data)
    
    def test_rsi_calculation(self, sample_data):
        """Проверка расчета RSI"""
        indicators = TechnicalIndicators()
        rsi = indicators.calculate_rsi(sample_data['close'], period=14)
        assert isinstance(rsi, pd.Series)
        assert len(rsi) == len(sample_data)


class TestIndicatorStrategy:
    """Минимальные тесты для IndicatorStrategy"""
    
    def test_import_and_instantiation(self):
        """Проверка импорта и создания экземпляра"""
        indicators = TechnicalIndicators()
        strategy = IndicatorStrategy(indicators)
        assert strategy is not None
    
    def test_trend_momentum_signal(self, sample_data):
        """Проверка работы trend_momentum_signal"""
        indicators = TechnicalIndicators()
        strategy = IndicatorStrategy(indicators)
        
        config = {
            'ema_short': 50,
            'ema_long': 200,
            'rsi_period': 14
        }
        
        result = strategy.trend_momentum_signal(sample_data, config)
        assert isinstance(result, dict)
        assert 'long_signal' in result
        assert 'short_signal' in result
        assert 'indicators' in result


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
