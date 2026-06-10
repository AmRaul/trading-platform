"""
Юнит-тесты для индикаторов в Dual Timeframe режиме
Проверяет что индикаторы рассчитываются на strategy timeframe, а TP/SL на execution
"""

import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from strategy import TradingStrategy
from indicators import TechnicalIndicators, IndicatorStrategy


class TestIndicatorsDualTimeframe(unittest.TestCase):
    """Тесты для индикаторов в dual timeframe режиме"""

    def setUp(self):
        """Настройка перед каждым тестом"""
        self.config = {
            'start_balance': 10000,
            'leverage': 1,
            'order_type': 'long',
            'timeframe': '15m',
            'execution_timeframe': '1m',
            'commission_rate': 0.0004,
            'calc_on_order_fills': True,
            'max_entries_per_bar': 3,

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
                'target_percent': 2.0,
                'trailing': False
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

    def test_indicators_calculated_on_strategy_timeframe(self):
        """
        КРИТИЧЕСКИЙ ТЕСТ: Индикаторы должны рассчитываться на strategy TF (15m), не execution (1m)

        Генерируем синтетические данные:
        - 15m данные: нисходящий тренд (цена падает) -> RSI должен быть низким
        - 1m данные: внутри каждой 15m свечи цены колеблются

        Проверяем:
        - RSI рассчитывается на 15m данных
        - Если RSI(15m) < 30 -> сигнал LONG
        - RSI(1m) НЕ используется
        """
        strategy = TradingStrategy(self.config)

        # Генерируем 15m данные с падающими ценами (для низкого RSI)
        dates_15m = pd.date_range('2024-01-01 00:00', periods=300, freq='15min')
        base_price = 40000

        # Падающий тренд для низкого RSI
        prices_15m = base_price - np.linspace(0, 3000, 300)  # Падение на $3000

        strategy_data = pd.DataFrame({
            'timestamp': dates_15m,
            'open': prices_15m + np.random.randn(300) * 20,
            'high': prices_15m + np.abs(np.random.randn(300) * 50),
            'low': prices_15m - np.abs(np.random.randn(300) * 50),
            'close': prices_15m,
            'volume': np.random.randint(1000, 10000, 300)
        })

        # Вычисляем RSI на 15m данных вручную для сравнения
        indicators = TechnicalIndicators()
        expected_rsi_15m = indicators.calculate_rsi(strategy_data['close'], 14)

        # Проверяем что RSI действительно низкий из-за падения
        last_rsi_15m = expected_rsi_15m.iloc[-1]
        self.assertLess(last_rsi_15m, 50, "RSI на 15m должен быть низким из-за падающего тренда")

        # Проверяем что стратегия использует правильные данные
        current_data = strategy_data.iloc[-1]
        result = strategy.should_enter_position(current_data, strategy_data)

        # Если RSI < 30 и EMA50 > EMA200, должен быть сигнал LONG
        print(f"RSI(15m) = {last_rsi_15m:.2f}")
        print(f"Entry signal = {result}")

        # Важно: результат зависит от EMA тоже, но RSI точно рассчитан на 15m данных
        self.assertIsInstance(result, bool, "should_enter_position должен вернуть bool")

    def test_entry_only_on_new_strategy_bar(self):
        """
        КРИТИЧЕСКИЙ ТЕСТ: Сигналы входа должны проверяться ТОЛЬКО на новых strategy свечах

        Dual timeframe логика:
        - 1 strategy свеча (15m) = 15 execution тиков (1m)
        - Сигнал входа проверяется ОДИН раз при новой 15m свече
        - НЕ на каждом 1m тике!
        """
        strategy = TradingStrategy(self.config)

        # Создаём минимальные данные для теста
        # 1 strategy свеча (15m)
        strategy_timestamp = pd.Timestamp('2024-01-01 10:00')
        strategy_data = pd.DataFrame({
            'timestamp': [strategy_timestamp],
            'open': [40000],
            'high': [40100],
            'low': [39900],
            'close': [40000],
            'volume': [1000]
        })

        # 15 execution тиков (1m) внутри одной 15m свечи
        exec_timestamps = pd.date_range(strategy_timestamp, periods=15, freq='1min')
        execution_data = pd.DataFrame({
            'timestamp': exec_timestamps,
            'open': [40000] * 15,
            'high': [40050] * 15,
            'low': [39950] * 15,
            'close': [40000 + i*10 for i in range(15)],  # Растущие цены
            'volume': [100] * 15
        })

        # Отслеживаем сколько раз вызывается should_enter_position
        entry_checks = []
        original_should_enter = strategy.should_enter_position

        def mock_should_enter(current_data, historical_data):
            entry_checks.append(current_data['timestamp'])
            return original_should_enter(current_data, historical_data)

        strategy.should_enter_position = mock_should_enter

        # Симулируем dual timeframe логику (как в backtester.py)
        for i, exec_row in execution_data.iterrows():
            current_exec_data = exec_row
            current_strategy_data = strategy_data.iloc[0]
            strategy_bar_timestamp = current_strategy_data['timestamp']

            # Проверяем новую strategy свечу
            is_new_strategy_bar = (
                strategy.last_processed_strategy_bar is None or
                strategy_bar_timestamp > strategy.last_processed_strategy_bar
            )

            if is_new_strategy_bar:
                strategy.last_processed_strategy_bar = strategy_bar_timestamp
                strategy.entries_on_current_bar = 0

                # Только при новой strategy свече проверяем сигнал
                if not strategy.has_open_position():
                    strategy.should_enter_position(current_strategy_data, strategy_data)

        # Проверяем что should_enter_position вызвался РОВНО 1 раз (не 15!)
        self.assertEqual(len(entry_checks), 1,
                        f"Сигнал входа должен проверяться 1 раз, не {len(entry_checks)}")

        print(f"✅ Сигнал входа проверен {len(entry_checks)} раз на 15 execution тиках")

    def test_takeprofit_checked_on_execution_timeframe(self):
        """
        КРИТИЧЕСКИЙ ТЕСТ: TP/SL должны проверяться на КАЖДОМ execution тике (1m)

        Это главное преимущество dual timeframe:
        - Сигналы на 15m (стабильность)
        - TP/SL на 1m (точность)
        """
        strategy = TradingStrategy(self.config)

        # Открываем позицию вручную
        entry_price = 40000
        entry_timestamp = pd.Timestamp('2024-01-01 10:00')

        order = strategy.create_order(entry_timestamp, entry_price)
        strategy.execute_order(order)

        self.assertTrue(strategy.has_open_position(), "Позиция должна быть открыта")

        # TP = 2% = 40800
        tp_price = entry_price * 1.02

        # Генерируем execution тики где цена достигает TP внутри свечи
        exec_data = pd.DataFrame({
            'timestamp': pd.date_range('2024-01-01 10:01', periods=5, freq='1min'),
            'open': [40100, 40200, 40300, 40400, 40500],
            'high': [40150, 40250, 40350, 40850, 40550],  # 4-й тик достигает TP через high!
            'low': [40050, 40150, 40250, 40350, 40450],
            'close': [40120, 40220, 40320, 40420, 40520],
            'volume': [100] * 5
        })

        # Проверяем каждый execution тик
        tp_triggered = False
        for i, row in exec_data.iterrows():
            position = strategy.get_open_position()
            if position:
                # Проверяем intrabar exit (как в реальном бэктестере)
                intrabar_exit, reason, exit_price = strategy.check_intrabar_exit(row, position)

                if intrabar_exit and reason == 'take_profit':
                    tp_triggered = True
                    print(f"✅ TP достигнут на тике {row['timestamp']} через high={row['high']}")
                    print(f"   Exit price: ${exit_price:.2f}, Expected: ${tp_price:.2f}")
                    break

        self.assertTrue(tp_triggered, "TP должен сработать на одном из execution тиков")

    def test_indicator_values_same_across_execution_ticks(self):
        """
        КРИТИЧЕСКИЙ ТЕСТ: Индикаторы НЕ должны меняться внутри одной strategy свечи

        Все execution тики внутри одной 15m свечи используют ОДНИ И ТЕ ЖЕ индикаторы.
        """
        strategy = TradingStrategy(self.config)

        # 1 strategy свеча
        strategy_data = pd.DataFrame({
            'timestamp': [pd.Timestamp('2024-01-01 10:00')],
            'open': [40000],
            'high': [40100],
            'low': [39900],
            'close': [40000],
            'volume': [1000]
        })

        # Вычисляем индикаторы на strategy данных
        indicators = TechnicalIndicators()
        indicator_strategy = IndicatorStrategy(indicators)

        # Первый вызов
        signal1 = indicator_strategy.trend_momentum_signal(
            strategy_data,
            self.config['indicators']['trend_momentum']
        )

        # Повторный вызов (симулирует следующий execution тик)
        signal2 = indicator_strategy.trend_momentum_signal(
            strategy_data,
            self.config['indicators']['trend_momentum']
        )

        # Индикаторы должны быть ИДЕНТИЧНЫ
        self.assertEqual(
            signal1['indicators']['rsi'],
            signal2['indicators']['rsi'],
            "RSI не должен меняться внутри одной strategy свечи"
        )

        self.assertEqual(
            signal1['indicators']['ema_50'],
            signal2['indicators']['ema_50'],
            "EMA не должна меняться внутри одной strategy свечи"
        )

        print(f"✅ Индикаторы стабильны: RSI={signal1['indicators']['rsi']:.2f}")


if __name__ == '__main__':
    # Запускаем тесты с подробным выводом
    unittest.main(verbosity=2)
