"""
Юнит-тесты для Dual Timeframe режима
Проверяет корректность работы dual timeframe логики и отсутствие look-ahead bias
"""

import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from data_loader import DataLoader


class TestDualTimeframeMode(unittest.TestCase):
    """Тесты для dual timeframe режима"""

    def setUp(self):
        """Настройка перед каждым тестом"""
        self.data_loader = DataLoader()

    def test_timeframe_to_timedelta(self):
        """Тест конвертации таймфреймов в timedelta"""
        test_cases = [
            ('1m', pd.Timedelta(minutes=1)),
            ('5m', pd.Timedelta(minutes=5)),
            ('15m', pd.Timedelta(minutes=15)),
            ('1h', pd.Timedelta(hours=1)),
            ('4h', pd.Timedelta(hours=4)),
            ('1d', pd.Timedelta(days=1)),
        ]

        for timeframe, expected_delta in test_cases:
            with self.subTest(timeframe=timeframe):
                result = self.data_loader._timeframe_to_timedelta(timeframe)
                self.assertEqual(result, expected_delta,
                               f"Timeframe {timeframe} должен конвертироваться в {expected_delta}")

    def test_timeframe_to_timedelta_invalid(self):
        """Тест на некорректный таймфрейм"""
        with self.assertRaises(ValueError):
            self.data_loader._timeframe_to_timedelta('99m')

    def test_get_parent_candle_index_no_lookahead_bias(self):
        """
        КРИТИЧЕСКИЙ ТЕСТ: Проверка отсутствия look-ahead bias

        Свеча с timestamp=10:00 для 15m таймфрейма означает период [10:00 - 10:15).
        Эта свеча закрывается только в момент 10:15.

        До момента 10:15 эта свеча НЕ должна использоваться (look-ahead bias!).
        """
        # Создаем тестовые данные для 15m таймфрейма
        strategy_data = pd.DataFrame({
            'timestamp': pd.to_datetime([
                '2024-01-01 09:30:00',  # [09:30 - 09:45)
                '2024-01-01 09:45:00',  # [09:45 - 10:00)
                '2024-01-01 10:00:00',  # [10:00 - 10:15) <- Эта свеча закрывается в 10:15
                '2024-01-01 10:15:00',  # [10:15 - 10:30)
            ]),
            'open': [100, 101, 102, 103],
            'high': [101, 102, 103, 104],
            'low': [99, 100, 101, 102],
            'close': [100.5, 101.5, 102.5, 103.5],
            'volume': [1000, 1100, 1200, 1300]
        })

        # Тест 1: Execution тик в 10:05 (внутри свечи 10:00)
        exec_timestamp_1005 = pd.to_datetime('2024-01-01 10:05:00')
        parent_idx_1005 = self.data_loader.get_parent_candle_index(
            exec_timestamp_1005, strategy_data, '15m'
        )

        # ✅ ПРАВИЛЬНО: Последняя закрытая свеча - это 09:45 (индекс 1)
        # ❌ НЕПРАВИЛЬНО: Свеча 10:00 (индекс 2) еще НЕ закрыта!
        self.assertEqual(parent_idx_1005, 1,
                        "Для execution тика 10:05 последняя закрытая 15m свеча - это 09:45, а не 10:00!")

        # Тест 2: Execution тик в 10:15 (момент закрытия свечи 10:00)
        exec_timestamp_1015 = pd.to_datetime('2024-01-01 10:15:00')
        parent_idx_1015 = self.data_loader.get_parent_candle_index(
            exec_timestamp_1015, strategy_data, '15m'
        )

        # ✅ ПРАВИЛЬНО: В момент 10:15 свеча 10:00 уже закрыта (индекс 2)
        self.assertEqual(parent_idx_1015, 2,
                        "Для execution тика 10:15 последняя закрытая свеча должна быть 10:00")

        # Тест 3: Execution тик в 10:14:59 (за 1 секунду до закрытия)
        exec_timestamp_10145959 = pd.to_datetime('2024-01-01 10:14:59')
        parent_idx_10145959 = self.data_loader.get_parent_candle_index(
            exec_timestamp_10145959, strategy_data, '15m'
        )

        # ✅ ПРАВИЛЬНО: За секунду до закрытия свеча еще не закрыта
        self.assertEqual(parent_idx_10145959, 1,
                        "За 1 секунду до закрытия свеча еще не должна быть доступна")

    def test_get_parent_candle_index_1m_to_15m(self):
        """Тест с реалистичными 1m -> 15m данными"""
        # 15m свечи
        strategy_data = pd.DataFrame({
            'timestamp': pd.to_datetime([
                '2024-01-01 10:00:00',  # [10:00 - 10:15)
                '2024-01-01 10:15:00',  # [10:15 - 10:30)
                '2024-01-01 10:30:00',  # [10:30 - 10:45)
            ]),
            'open': [100, 101, 102],
            'high': [101, 102, 103],
            'low': [99, 100, 101],
            'close': [100.5, 101.5, 102.5],
            'volume': [1000, 1100, 1200]
        })

        # Тестируем разные 1m тики
        test_cases = [
            ('2024-01-01 10:01:00', -1),   # До первой закрытой свечи
            ('2024-01-01 10:14:00', -1),   # Внутри первой свечи
            ('2024-01-01 10:15:00', 0),    # Момент закрытия первой свечи
            ('2024-01-01 10:16:00', 0),    # Внутри второй свечи
            ('2024-01-01 10:29:59', 0),    # За секунду до закрытия второй
            ('2024-01-01 10:30:00', 1),    # Момент закрытия второй свечи
            ('2024-01-01 10:31:00', 1),    # Внутри третьей свечи
        ]

        for exec_time_str, expected_idx in test_cases:
            with self.subTest(exec_time=exec_time_str):
                exec_timestamp = pd.to_datetime(exec_time_str)
                result_idx = self.data_loader.get_parent_candle_index(
                    exec_timestamp, strategy_data, '15m'
                )
                self.assertEqual(result_idx, expected_idx,
                               f"Для execution тика {exec_time_str} ожидается индекс {expected_idx}")

    def test_get_parent_candle_index_1m_to_1h(self):
        """Тест с 1m -> 1h данными"""
        # 1h свечи
        strategy_data = pd.DataFrame({
            'timestamp': pd.to_datetime([
                '2024-01-01 09:00:00',  # [09:00 - 10:00)
                '2024-01-01 10:00:00',  # [10:00 - 11:00)
                '2024-01-01 11:00:00',  # [11:00 - 12:00)
            ]),
            'open': [100, 101, 102],
            'high': [101, 102, 103],
            'low': [99, 100, 101],
            'close': [100.5, 101.5, 102.5],
            'volume': [1000, 1100, 1200]
        })

        # Тестируем
        test_cases = [
            ('2024-01-01 09:30:00', -1),   # Внутри первой свечи
            ('2024-01-01 09:59:59', -1),   # За секунду до закрытия
            ('2024-01-01 10:00:00', 0),    # Момент закрытия первой свечи
            ('2024-01-01 10:30:00', 0),    # Внутри второй свечи
            ('2024-01-01 10:59:59', 0),    # За секунду до закрытия второй
            ('2024-01-01 11:00:00', 1),    # Момент закрытия второй свечи
        ]

        for exec_time_str, expected_idx in test_cases:
            with self.subTest(exec_time=exec_time_str):
                exec_timestamp = pd.to_datetime(exec_time_str)
                result_idx = self.data_loader.get_parent_candle_index(
                    exec_timestamp, strategy_data, '1h'
                )
                self.assertEqual(result_idx, expected_idx,
                               f"Для execution тика {exec_time_str} ожидается индекс {expected_idx}")

    def test_resample_to_timeframe_1m_to_15m(self):
        """Тест ресемплинга 1m -> 15m"""
        # Создаем 1m данные (15 минут = 15 свечей)
        start_time = pd.to_datetime('2024-01-01 10:00:00')
        timestamps = [start_time + pd.Timedelta(minutes=i) for i in range(15)]

        data_1m = pd.DataFrame({
            'timestamp': timestamps,
            'open': [100 + i * 0.1 for i in range(15)],
            'high': [100.5 + i * 0.1 for i in range(15)],
            'low': [99.5 + i * 0.1 for i in range(15)],
            'close': [100.2 + i * 0.1 for i in range(15)],
            'volume': [100 for _ in range(15)]
        })

        # Ресемплируем в 15m
        data_15m = self.data_loader.resample_to_timeframe(data_1m, '15m')

        # Проверки
        self.assertEqual(len(data_15m), 1, "Должна быть 1 свеча 15m из 15 свечей 1m")
        self.assertEqual(data_15m.iloc[0]['timestamp'], start_time,
                        "Timestamp должен быть на начале периода")
        self.assertEqual(data_15m.iloc[0]['open'], data_1m.iloc[0]['open'],
                        "Open должен быть из первой 1m свечи")
        self.assertEqual(data_15m.iloc[0]['close'], data_1m.iloc[-1]['close'],
                        "Close должен быть из последней 1m свечи")
        self.assertEqual(data_15m.iloc[0]['high'], data_1m['high'].max(),
                        "High должен быть максимальным из всех 1m свечей")
        self.assertEqual(data_15m.iloc[0]['low'], data_1m['low'].min(),
                        "Low должен быть минимальным из всех 1m свечей")
        self.assertEqual(data_15m.iloc[0]['volume'], data_1m['volume'].sum(),
                        "Volume должен быть суммой всех 1m свечей")

    def test_resample_alignment(self):
        """Тест правильности alignment при ресемплинге"""
        # Создаем данные с конкретными временами
        data_1m = pd.DataFrame({
            'timestamp': pd.to_datetime([
                '2024-01-01 10:00:00',
                '2024-01-01 10:01:00',
                '2024-01-01 10:02:00',
                '2024-01-01 10:15:00',  # Следующий период
                '2024-01-01 10:16:00',
            ]),
            'open': [100, 101, 102, 103, 104],
            'high': [100.5, 101.5, 102.5, 103.5, 104.5],
            'low': [99.5, 100.5, 101.5, 102.5, 103.5],
            'close': [100.2, 101.2, 102.2, 103.2, 104.2],
            'volume': [100, 100, 100, 100, 100]
        })

        # Ресемплируем в 15m
        data_15m = self.data_loader.resample_to_timeframe(data_1m, '15m')

        # Должно быть 2 свечи
        self.assertEqual(len(data_15m), 2, "Должно быть 2 свечи 15m")

        # Первая свеча должна начинаться с 10:00
        self.assertEqual(data_15m.iloc[0]['timestamp'],
                        pd.to_datetime('2024-01-01 10:00:00'),
                        "Первая свеча должна иметь timestamp 10:00")

        # Вторая свеча должна начинаться с 10:15
        self.assertEqual(data_15m.iloc[1]['timestamp'],
                        pd.to_datetime('2024-01-01 10:15:00'),
                        "Вторая свеча должна иметь timestamp 10:15")


class TestDualTimeframeIntegration(unittest.TestCase):
    """Интеграционные тесты для полного dual timeframe workflow"""

    def setUp(self):
        """Настройка перед каждым тестом"""
        self.data_loader = DataLoader()

    def test_full_dual_timeframe_workflow(self):
        """Тест полного workflow: resample + get_parent_candle"""
        # Создаем 1m данные (1 час = 60 свечей)
        start_time = pd.to_datetime('2024-01-01 10:00:00')
        timestamps = [start_time + pd.Timedelta(minutes=i) for i in range(60)]

        execution_data = pd.DataFrame({
            'timestamp': timestamps,
            'open': [100 + i * 0.01 for i in range(60)],
            'high': [100.5 + i * 0.01 for i in range(60)],
            'low': [99.5 + i * 0.01 for i in range(60)],
            'close': [100.2 + i * 0.01 for i in range(60)],
            'volume': [100 for _ in range(60)]
        })

        # Ресемплируем в 15m
        strategy_data = self.data_loader.resample_to_timeframe(execution_data, '15m')

        # Должно быть 4 свечи 15m
        self.assertEqual(len(strategy_data), 4, "Должно быть 4 свечи 15m из 60 свечей 1m")

        # Тестируем что для каждой 1m свечи мы получаем правильную strategy свечу
        for i, exec_row in execution_data.iterrows():
            exec_timestamp = exec_row['timestamp']
            parent_idx = self.data_loader.get_parent_candle_index(
                exec_timestamp, strategy_data, '15m'
            )

            # Вычисляем ожидаемый индекс
            minutes_from_start = (exec_timestamp - start_time).total_seconds() / 60
            expected_idx = int(minutes_from_start // 15) - 1  # -1 потому что свеча еще не закрыта

            # Для первых 15 минут нет закрытых свечей
            if minutes_from_start < 15:
                expected_idx = -1

            self.assertEqual(parent_idx, expected_idx,
                           f"Для execution тика {exec_timestamp} ожидается parent_idx={expected_idx}, "
                           f"получено {parent_idx}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
