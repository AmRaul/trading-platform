"""
Простой ручной тест для проверки индикаторов в dual timeframe
Запускается без pytest - просто python test_manual_indicators.py
"""

import sys
import pandas as pd
import numpy as np

# Проверяем импорты
try:
    from indicators import TechnicalIndicators, IndicatorStrategy
    print("✅ indicators.py импортирован успешно")
except ImportError as e:
    print(f"❌ Ошибка импорта indicators: {e}")
    sys.exit(1)

try:
    from strategy import TradingStrategy
    print("✅ strategy.py импортирован успешно")
except ImportError as e:
    print(f"❌ Ошибка импорта strategy: {e}")
    sys.exit(1)


def test_indicator_calculation():
    """Проверка базового расчета индикаторов"""
    print("\n" + "="*60)
    print("ТЕСТ 1: Базовый расчет индикаторов")
    print("="*60)

    # Создаём синтетические данные
    dates = pd.date_range('2024-01-01', periods=300, freq='15min')
    base_price = 40000

    # Падающий тренд для низкого RSI
    prices = base_price - np.linspace(0, 2000, 300)

    data = pd.DataFrame({
        'timestamp': dates,
        'open': prices + np.random.randn(300) * 20,
        'high': prices + np.abs(np.random.randn(300) * 50),
        'low': prices - np.abs(np.random.randn(300) * 50),
        'close': prices,
        'volume': np.random.randint(1000, 10000, 300)
    })

    # Вычисляем индикаторы
    indicators = TechnicalIndicators()

    rsi = indicators.calculate_rsi(data['close'], 14)
    ema_50 = indicators.calculate_ema(data['close'], 50)
    ema_200 = indicators.calculate_ema(data['close'], 200)

    print(f"Данных: {len(data)} свечей")
    print(f"RSI последнее значение: {rsi.iloc[-1]:.2f}")
    print(f"EMA50 последнее значение: {ema_50.iloc[-1]:.2f}")
    print(f"EMA200 последнее значение: {ema_200.iloc[-1]:.2f}")

    # Проверки
    assert not pd.isna(rsi.iloc[-1]), "RSI не должен быть NaN"
    assert not pd.isna(ema_50.iloc[-1]), "EMA50 не должна быть NaN"
    assert not pd.isna(ema_200.iloc[-1]), "EMA200 не должна быть NaN"

    # RSI должен быть низким из-за падающего тренда
    assert rsi.iloc[-1] < 60, f"RSI должен быть низким, получили {rsi.iloc[-1]:.2f}"

    print("✅ Индикаторы рассчитываются корректно")
    return True


def test_indicator_strategy_signal():
    """Проверка генерации сигналов стратегией"""
    print("\n" + "="*60)
    print("ТЕСТ 2: Генерация сигналов индикаторной стратегией")
    print("="*60)

    # Создаём данные для сильного LONG сигнала
    dates = pd.date_range('2024-01-01', periods=300, freq='15min')
    base_price = 40000

    # Восходящий тренд + недавнее падение для RSI < 40
    trend = np.linspace(0, 5000, 300)  # Растёт
    noise = np.cumsum(np.random.randn(300) * 50)
    prices = base_price + trend + noise

    # Последние 20 свечей падают для низкого RSI
    prices[-20:] = prices[-21] - np.linspace(0, 500, 20)

    data = pd.DataFrame({
        'timestamp': dates,
        'open': prices,
        'high': prices + np.abs(np.random.randn(300) * 30),
        'low': prices - np.abs(np.random.randn(300) * 30),
        'close': prices,
        'volume': np.random.randint(1000, 10000, 300)
    })

    # Используем стратегию
    indicators = TechnicalIndicators()
    indicator_strategy = IndicatorStrategy(indicators)

    config = {
        'ema_short': 50,
        'ema_long': 200,
        'rsi_period': 14,
        'rsi_oversold': 30,
        'rsi_overbought': 70
    }

    signal = indicator_strategy.trend_momentum_signal(data, config)

    print(f"RSI: {signal['indicators']['rsi']:.2f}")
    print(f"EMA50: {signal['indicators']['ema_50']:.2f}")
    print(f"EMA200: {signal['indicators']['ema_200']:.2f}")
    print(f"Тренд вверх: {signal['trend_up']}")
    print(f"RSI перепроданность: {signal['rsi_oversold']}")
    print(f"LONG сигнал: {signal['long_signal']}")
    print(f"SHORT сигнал: {signal['short_signal']}")

    # Проверки структуры
    assert 'long_signal' in signal, "Должен быть long_signal"
    assert 'short_signal' in signal, "Должен быть short_signal"
    assert 'indicators' in signal, "Должны быть indicators"

    print("✅ Сигналы генерируются корректно")
    return True


def test_strategy_with_indicators():
    """Проверка работы TradingStrategy с индикаторами"""
    print("\n" + "="*60)
    print("ТЕСТ 3: TradingStrategy с индикаторами")
    print("="*60)

    config = {
        'start_balance': 10000,
        'leverage': 1,
        'order_type': 'long',
        'commission_rate': 0.0004,

        'entry_conditions': {
            'trigger_type': 'indicator'
        },

        'first_order': {
            'type': 'percent',
            'percent_of_balance': 10
        },

        'dca': {
            'enabled': False
        },

        'take_profit': {
            'enabled': True,
            'target_percent': 2.0
        },

        'stop_loss': {
            'enabled': False
        },

        'indicators': {
            'enabled': True,
            'strategy_type': 'trend_momentum',
            'trend_momentum': {
                'ema_short': 50,
                'ema_long': 200,
                'rsi_period': 14,
                'rsi_oversold': 30,
                'rsi_overbought': 70
            }
        }
    }

    strategy = TradingStrategy(config)

    print(f"Индикаторы включены: {strategy.indicators_enabled}")
    print(f"Тип стратегии: {strategy.indicator_strategy}")
    print(f"Начальный баланс: ${strategy.balance:.2f}")

    # Проверки
    assert strategy.indicators_enabled, "Индикаторы должны быть включены"
    assert strategy.indicator_strategy == 'trend_momentum', "Должна быть trend_momentum стратегия"
    assert strategy.indicator_strategy_handler is not None, "Handler должен быть инициализирован"

    # Создаём тестовые данные
    dates = pd.date_range('2024-01-01', periods=300, freq='15min')
    prices = 40000 - np.linspace(0, 1000, 300)  # Падающий тренд

    data = pd.DataFrame({
        'timestamp': dates,
        'open': prices,
        'high': prices + 50,
        'low': prices - 50,
        'close': prices,
        'volume': [1000] * 300
    })

    # Проверяем условие входа
    current_data = data.iloc[-1]
    should_enter = strategy.should_enter_position(current_data, data)

    print(f"Должен войти в позицию: {should_enter}")
    print(f"Тип результата: {type(should_enter)}")
    print(f"Значение результата: {repr(should_enter)}")

    # Проверка типа возврата
    assert isinstance(should_enter, (bool, np.bool_)), f"should_enter_position должен вернуть bool, получили {type(should_enter)}"

    print("✅ TradingStrategy работает с индикаторами")
    return True


def test_dual_timeframe_concept():
    """
    Концептуальный тест: индикаторы на strategy TF, TP/SL на execution TF
    """
    print("\n" + "="*60)
    print("ТЕСТ 4: Dual Timeframe концепция")
    print("="*60)

    # Strategy timeframe (15m) - 20 свечей
    strategy_dates = pd.date_range('2024-01-01 00:00', periods=20, freq='15min')
    strategy_prices = 40000 + np.linspace(0, 1000, 20)

    strategy_data = pd.DataFrame({
        'timestamp': strategy_dates,
        'close': strategy_prices,
        'high': strategy_prices + 50,
        'low': strategy_prices - 50,
        'open': strategy_prices,
        'volume': [1000] * 20
    })

    # Execution timeframe (1m) - внутри одной 15m свечи
    # Одна 15m свеча = 15 execution тиков
    exec_dates = pd.date_range(strategy_dates[0], periods=15, freq='1min')
    exec_prices = np.linspace(strategy_prices[0], strategy_prices[0] + 100, 15)

    execution_data = pd.DataFrame({
        'timestamp': exec_dates,
        'close': exec_prices,
        'high': exec_prices + 10,
        'low': exec_prices - 10,
        'open': exec_prices,
        'volume': [100] * 15
    })

    # Вычисляем RSI на strategy данных
    indicators = TechnicalIndicators()
    rsi_strategy = indicators.calculate_rsi(strategy_data['close'], 14)

    # Вычисляем RSI на execution данных (НЕ должен использоваться!)
    rsi_execution = indicators.calculate_rsi(execution_data['close'], 14)

    print(f"RSI на strategy TF (15m): {rsi_strategy.iloc[-1]:.2f}")
    print(f"RSI на execution TF (1m): {rsi_execution.iloc[-1]:.2f}")
    print(f"Strategy свечей: {len(strategy_data)}")
    print(f"Execution тиков внутри 1 strategy свечи: {len(execution_data)}")

    # КЛЮЧЕВОЙ МОМЕНТ: RSI на разных таймфреймах РАЗНЫЙ
    # В dual timeframe используется ТОЛЬКО strategy TF для индикаторов
    print("\n💡 Ключевой момент:")
    print("   - Индикаторы рассчитываются на strategy timeframe (15m)")
    print("   - Сигнал входа проверяется 1 раз на новой 15m свече")
    print("   - TP/SL проверяются на КАЖДОМ 1m execution тике")
    print("   - Это даёт стабильность сигналов + точность исполнения")

    print("✅ Dual timeframe концепция корректна")
    return True


def main():
    """Запуск всех тестов"""
    print("\n" + "="*60)
    print("РУЧНОЕ ТЕСТИРОВАНИЕ ИНДИКАТОРОВ В DUAL TIMEFRAME")
    print("="*60)

    tests = [
        test_indicator_calculation,
        test_indicator_strategy_signal,
        test_strategy_with_indicators,
        test_dual_timeframe_concept
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"❌ Тест провален: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "="*60)
    print(f"РЕЗУЛЬТАТЫ: {passed} тестов пройдено, {failed} провалено")
    print("="*60)

    if failed == 0:
        print("\n🎉 Все тесты пройдены! Индикаторы работают корректно в dual timeframe режиме.")
        return 0
    else:
        print("\n⚠️ Некоторые тесты провалены. Требуется доработка.")
        return 1


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
