"""
Модуль для расчета технических индикаторов
Использует библиотеку ta для быстрых и точных вычислений
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
import ta

class TechnicalIndicators:
    """
    Класс для расчета технических индикаторов
    Использует библиотеку ta для оптимизированных вычислений
    """
    
    def __init__(self):
        self.cache = {}  # Кэш для хранения вычисленных индикаторов
    
    def calculate_ema(self, data: pd.Series, period: int, cache_key: str = None) -> pd.Series:
        """
        Вычисляет Exponential Moving Average (EMA)
        
        Args:
            data: серия цен (обычно close)
            period: период EMA
            cache_key: ключ для кэширования (опционально)
            
        Returns:
            pd.Series с EMA значениями
        """
        if cache_key and cache_key in self.cache:
            return self.cache[cache_key]
        
        ema = ta.trend.EMAIndicator(close=data, window=period).ema_indicator()
        
        if cache_key:
            self.cache[cache_key] = ema
            
        return ema
    
    def calculate_rsi(self, data: pd.Series, period: int = 14, cache_key: str = None) -> pd.Series:
        """
        Вычисляет Relative Strength Index (RSI)
        
        Args:
            data: серия цен (обычно close)
            period: период RSI (по умолчанию 14)
            cache_key: ключ для кэширования (опционально)
            
        Returns:
            pd.Series с RSI значениями (0-100)
        """
        if cache_key and cache_key in self.cache:
            return self.cache[cache_key]
        
        rsi = ta.momentum.RSIIndicator(close=data, window=period).rsi()
        
        if cache_key:
            self.cache[cache_key] = rsi
            
        return rsi
    
    def calculate_bollinger_bands(self, data: pd.Series, period: int = 20, 
                                std_dev: float = 2, cache_key: str = None) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Вычисляет Bollinger Bands
        
        Args:
            data: серия цен (обычно close)
            period: период для SMA
            std_dev: количество стандартных отклонений
            cache_key: ключ для кэширования (опционально)
            
        Returns:
            Tuple (upper_band, middle_band, lower_band)
        """
        if cache_key and cache_key in self.cache:
            return self.cache[cache_key]
        
        bb = ta.volatility.BollingerBands(close=data, window=period, window_dev=std_dev)
        upper = bb.bollinger_hband()
        middle = bb.bollinger_mavg()
        lower = bb.bollinger_lband()
        
        result = (upper, middle, lower)
        
        if cache_key:
            self.cache[cache_key] = result
            
        return result
    
    def calculate_atr(self, high: pd.Series, low: pd.Series, close: pd.Series,
                     period: int = 14, cache_key: str = None) -> pd.Series:
        """
        Вычисляет Average True Range (ATR)

        Args:
            high: серия максимальных цен
            low: серия минимальных цен
            close: серия цен закрытия
            period: период ATR
            cache_key: ключ для кэширования (опционально)

        Returns:
            pd.Series с ATR значениями
        """
        if cache_key and cache_key in self.cache:
            return self.cache[cache_key]

        atr = ta.volatility.AverageTrueRange(high=high, low=low, close=close, window=period).average_true_range()

        if cache_key:
            self.cache[cache_key] = atr

        return atr

    def calculate_adx(self, high: pd.Series, low: pd.Series, close: pd.Series,
                     period: int = 14, cache_key: str = None) -> pd.Series:
        """
        Вычисляет Average Directional Index (ADX)
        Измеряет силу тренда (не направление) от 0 до 100
        ADX > 25 = сильный тренд, ADX < 25 = слабый тренд/флет

        Args:
            high: серия максимальных цен
            low: серия минимальных цен
            close: серия цен закрытия
            period: период ADX (по умолчанию 14)
            cache_key: ключ для кэширования (опционально)

        Returns:
            pd.Series с ADX значениями (0-100)
        """
        if cache_key and cache_key in self.cache:
            return self.cache[cache_key]

        adx_indicator = ta.trend.ADXIndicator(high=high, low=low, close=close, window=period)
        adx = adx_indicator.adx()

        if cache_key:
            self.cache[cache_key] = adx

        return adx
    
    def calculate_supertrend(self, high: pd.Series, low: pd.Series, close: pd.Series,
                           period: int = 10, multiplier: float = 3, cache_key: str = None) -> Tuple[pd.Series, pd.Series]:
        """
        Вычисляет SuperTrend индикатор

        Args:
            high: серия максимальных цен
            low: серия минимальных цен
            close: серия цен закрытия
            period: период ATR для SuperTrend
            multiplier: множитель ATR
            cache_key: ключ для кэширования (опционально)

        Returns:
            Tuple (supertrend_line, direction)
        """
        if cache_key and cache_key in self.cache:
            return self.cache[cache_key]

        # Реализуем SuperTrend вручную
        # Вычисляем ATR
        atr = ta.volatility.AverageTrueRange(high=high, low=low, close=close, window=period).average_true_range()

        # Вычисляем базовые полосы
        hl2 = (high + low) / 2
        upper_band = hl2 + (multiplier * atr)
        lower_band = hl2 - (multiplier * atr)

        # Инициализируем массивы
        supertrend_line = pd.Series(index=close.index, dtype=float)
        direction = pd.Series(index=close.index, dtype=float)

        # Первое значение
        supertrend_line.iloc[0] = upper_band.iloc[0]
        direction.iloc[0] = 1

        # Вычисляем SuperTrend
        for i in range(1, len(close)):
            # Определяем направление тренда
            if close.iloc[i] > supertrend_line.iloc[i-1]:
                direction.iloc[i] = 1  # Восходящий тренд
                supertrend_line.iloc[i] = lower_band.iloc[i] if lower_band.iloc[i] > supertrend_line.iloc[i-1] else supertrend_line.iloc[i-1]
            else:
                direction.iloc[i] = -1  # Нисходящий тренд
                supertrend_line.iloc[i] = upper_band.iloc[i] if upper_band.iloc[i] < supertrend_line.iloc[i-1] else supertrend_line.iloc[i-1]

        result = (supertrend_line, direction)
        
        if cache_key:
            self.cache[cache_key] = result
            
        return result
    
    def calculate_stochastic_rsi(self, data: pd.Series, k_period: int = 14, d_period: int = 3,
                               rsi_period: int = 14, cache_key: str = None) -> Tuple[pd.Series, pd.Series]:
        """
        Вычисляет Stochastic RSI
        
        Args:
            data: серия цен (обычно close)
            k_period: период %K
            d_period: период %D
            rsi_period: период RSI
            cache_key: ключ для кэширования (опционально)
            
        Returns:
            Tuple (%K, %D)
        """
        if cache_key and cache_key in self.cache:
            return self.cache[cache_key]
        
        stoch_rsi = ta.momentum.StochRSIIndicator(
            close=data, window=k_period, smooth1=d_period, smooth2=d_period
        )
        
        k_percent = stoch_rsi.stochrsi_k()
        d_percent = stoch_rsi.stochrsi_d()
        
        result = (k_percent, d_percent)
        
        if cache_key:
            self.cache[cache_key] = result
            
        return result
    
    def calculate_macd(self, data: pd.Series, fast_period: int = 12, slow_period: int = 26,
                      signal_period: int = 9, cache_key: str = None) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Вычисляет MACD (Moving Average Convergence Divergence)
        
        Args:
            data: серия цен (обычно close)
            fast_period: период быстрой EMA
            slow_period: период медленной EMA
            signal_period: период сигнальной линии
            cache_key: ключ для кэширования (опционально)
            
        Returns:
            Tuple (macd_line, signal_line, histogram)
        """
        if cache_key and cache_key in self.cache:
            return self.cache[cache_key]
        
        macd = ta.trend.MACD(
            close=data, window_fast=fast_period, window_slow=slow_period, window_sign=signal_period
        )
        
        macd_line = macd.macd()
        signal_line = macd.macd_signal()
        histogram = macd.macd_diff()
        
        result = (macd_line, signal_line, histogram)
        
        if cache_key:
            self.cache[cache_key] = result
            
        return result
    
    def _supersmoother(self, src: pd.Series, length: int) -> pd.Series:
        """
        SuperSmoother (Ehlers) — двухполюсный low-lag фильтр.
        Рекурсивен по 2 предыдущим ВЫХОДНЫМ значениям, не векторизуется —
        цикл по барам неизбежен (аналог calculate_supertrend выше).

        Cold-start: out[0] = src[0], out[1] = src[1] (не NaN, оба бара
        напрямую из источника, БЕЗ частичного применения рекурсии) —
        стандартная практика для двухполюсных Ehlers-фильтров. Инициализация
        out[1] через частичную формулу (c1*src[1] + c2*out[0], без c3) даёт
        выброс на разгоне при постоянном входе (проверено эмпирически —
        c2≈1.96 при length=200 даёт out[1]≈195 вместо 100, и система
        затухает к истинному значению только через сотни баров вместо
        мгновенной сходимости). Сходится за ~length баров.
        """
        a1 = np.exp(-np.sqrt(2) * np.pi / length)
        b1 = 2 * a1 * np.cos(np.sqrt(2) * np.pi / length)
        c3 = -a1 ** 2
        c2 = b1
        c1 = 1 - c2 - c3

        src_vals = src.values
        out = np.empty(len(src_vals), dtype=float)
        for i in range(len(src_vals)):
            if i == 0:
                out[i] = src_vals[i]
            elif i == 1:
                out[i] = src_vals[i]
            else:
                out[i] = c1 * src_vals[i] + c2 * out[i - 1] + c3 * out[i - 2]

        return pd.Series(out, index=src.index)

    def calculate_mrc(self, df: pd.DataFrame, length: int = 200,
                       inner_mult: float = 1.0, outer_mult: float = 2.415,
                       gradsize: float = 0.5, source: str = 'hlc3',
                       cache_key: str = None) -> pd.DataFrame:
        """
        Вычисляет Mean Reversion Channel (MRC), перенесено из PineScript
        индикатора "AT-MRC Platon" (см. algoTrading/mrc_btc_15m_overbought_oversold.txt
        для полной формулы и обоснования — источник истины для этой реализации).

        Args:
            df: DataFrame с колонками high, low, close (и open если source='ohlc4')
            length: период SuperSmoother (по умолчанию 200)
            inner_mult: множитель внутренней полосы (по умолчанию 1.0)
            outer_mult: множитель внешней полосы (по умолчанию 2.415)
            gradsize: шаг ступени zone-сетки в единицах meanrange (по умолчанию 0.5)
            source: источник цены — 'hlc3' | 'close' | 'ohlc4'
            cache_key: ключ для кэширования (опционально; в бэктесте всегда None —
                см. остальные indicator-методы этого файла)

        Returns:
            pd.DataFrame (тот же индекс, что и df) с колонками:
            meanline, meanrange, upband1, loband1, upband2, loband2, risk_zone
        """
        if cache_key and cache_key in self.cache:
            return self.cache[cache_key]

        high, low, close = df['high'], df['low'], df['close']

        if source == 'close':
            src = close
        elif source == 'ohlc4':
            src = (df['open'] + high + low + close) / 4
        else:  # hlc3 (по умолчанию — соответствует настройке живого индикатора)
            src = (high + low + close) / 3

        # True Range — СВЕЖИЙ ручной расчёт, не через calculate_atr(): тот уже
        # сглаживает TR внутри (RMA/Wilder), а SuperSmoother должен получать
        # сырой TR и сглаживать его сам, иначе двойное сглаживание разойдётся
        # с оригинальным PineScript-расчётом (там SuperSmoother(ta.tr, ...), не ta.atr).
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        tr.iloc[0] = high.iloc[0] - low.iloc[0]  # нет prev_close для бара 0

        meanline = self._supersmoother(src, length)
        meanrange = self._supersmoother(tr, length)

        mult = np.pi * inner_mult
        mult2 = np.pi * outer_mult
        upband1 = meanline + meanrange * mult
        loband1 = meanline - meanrange * mult
        upband2 = meanline + meanrange * mult2
        loband2 = meanline - meanrange * mult2

        # risk_zone (1..5, зеркально -1..-5) — классификация по шагам
        # meanrange*gradsize вокруг outer band, см. mrc_btc_15m_overbought_oversold.txt §4
        step = meanrange * gradsize
        upband2_1 = upband2 + step * 4   # самая дальняя ступень (extreme)
        loband2_1 = loband2 - step * 4

        above_mean = close > meanline
        below_mean = close < meanline

        # Сторона above_mean (overbought: risk_zone положительный)
        ob_conditions = [
            close >= upband2_1,                                    # extreme overbought
            close >= upband2,                                      # medium overbought (upband2 <= close < upband2_1)
            close > upband2 - step * 8,                            # light overbought (за outer band, ещё не дошли до upband2)
            close <= meanline + meanrange,                         # near mean
        ]
        ob_choices = [3, 2, 1, 4]
        risk_zone_above = np.select(ob_conditions, ob_choices, default=5)  # above mean, вне зон 1-4

        # Сторона below_mean (oversold: risk_zone отрицательный), зеркально
        os_conditions = [
            close <= loband2_1,
            close <= loband2,
            close < loband2 + step * 8,
            close >= meanline - meanrange,
        ]
        os_choices = [-3, -2, -1, -4]
        risk_zone_below = np.select(os_conditions, os_choices, default=-5)

        risk_zone = pd.Series(
            np.where(above_mean, risk_zone_above, np.where(below_mean, risk_zone_below, 0)),
            index=df.index,
        )

        result = pd.DataFrame({
            'meanline': meanline,
            'meanrange': meanrange,
            'upband1': upband1,
            'loband1': loband1,
            'upband2': upband2,
            'loband2': loband2,
            'risk_zone': risk_zone,
        }, index=df.index)

        if cache_key:
            self.cache[cache_key] = result

        return result

    def clear_cache(self):
        """Очищает кэш индикаторов"""
        self.cache.clear()
    
    def get_cached_indicators(self) -> List[str]:
        """Возвращает список закэшированных индикаторов"""
        return list(self.cache.keys())


class IndicatorStrategy:
    """
    Класс для работы со стратегиями на основе индикаторов
    """
    
    def __init__(self, indicators: TechnicalIndicators):
        self.indicators = indicators
    
    def trend_momentum_signal(self, data: pd.DataFrame, config: dict) -> dict:
        """
        Стратегия: Тренд + импульс (EMA + RSI)
        
        Args:
            data: DataFrame с OHLCV данными
            config: конфигурация стратегии
            
        Returns:
            dict с сигналами и значениями индикаторов
        """
        # Получаем параметры
        ema_short = config.get('ema_short', 50)
        ema_long = config.get('ema_long', 200)
        rsi_period = config.get('rsi_period', 14)
        rsi_oversold = config.get('rsi_oversold', 30)
        rsi_overbought = config.get('rsi_overbought', 70)
        
        # Вычисляем индикаторы (БЕЗ кэширования для корректной работы в бэктесте)
        ema_50 = self.indicators.calculate_ema(
            data['close'], ema_short, cache_key=None
        )
        ema_200 = self.indicators.calculate_ema(
            data['close'], ema_long, cache_key=None
        )
        rsi = self.indicators.calculate_rsi(
            data['close'], rsi_period, cache_key=None
        )
        
        # Получаем текущие значения (используем -1 для последнего элемента)
        if len(data) == 0 or len(ema_50) == 0 or len(ema_200) == 0 or len(rsi) == 0:
            return {
                'long_signal': False,
                'short_signal': False,
                'trend_up': False,
                'trend_down': False,
                'rsi_oversold': False,
                'rsi_overbought': False,
                'indicators': {
                    'ema_50': 0,
                    'ema_200': 0,
                    'rsi': 0,
                    'ema_50_series': ema_50,
                    'ema_200_series': ema_200,
                    'rsi_series': rsi
                }
            }

        # Проверяем, что у нас достаточно данных
        if pd.isna(ema_50.iloc[-1]) or pd.isna(ema_200.iloc[-1]) or pd.isna(rsi.iloc[-1]):
            return {
                'long_signal': False,
                'short_signal': False,
                'trend_up': False,
                'trend_down': False,
                'rsi_oversold': False,
                'rsi_overbought': False,
                'indicators': {
                    'ema_50': 0,
                    'ema_200': 0,
                    'rsi': 0,
                    'ema_50_series': ema_50,
                    'ema_200_series': ema_200,
                    'rsi_series': rsi
                }
            }

        ema_50_current = ema_50.iloc[-1]
        ema_200_current = ema_200.iloc[-1]
        rsi_current = rsi.iloc[-1]
        
        # Определяем тренд
        trend_up = ema_50_current > ema_200_current
        trend_down = ema_50_current < ema_200_current

        # Определяем сигналы (используем настройки из конфига)
        long_signal = trend_up and rsi_current < rsi_oversold
        short_signal = trend_down and rsi_current > rsi_overbought
        
        # Отладочная информация (закомментирована чтобы не спамить)
        # print(f"DEBUG: EMA50={ema_50_current:.2f}, EMA200={ema_200_current:.2f}, RSI={rsi_current:.2f}")
        # print(f"DEBUG: trend_up={trend_up}, trend_down={trend_down}")
        # print(f"DEBUG: long_signal={long_signal}, short_signal={short_signal}")
        
        return {
            'long_signal': long_signal,
            'short_signal': short_signal,
            'trend_up': trend_up,
            'trend_down': trend_down,
            'rsi_oversold': rsi_current < rsi_oversold,
            'rsi_overbought': rsi_current > rsi_overbought,
            'indicators': {
                'ema_50': ema_50_current,
                'ema_200': ema_200_current,
                'rsi': rsi_current,
                'ema_50_series': ema_50,
                'ema_200_series': ema_200,
                'rsi_series': rsi
            }
        }
    
    def volatility_bounce_signal(self, data: pd.DataFrame, config: dict) -> dict:
        """
        Стратегия: Волатильность + отскок (Bollinger Bands + ATR)
        
        Args:
            data: DataFrame с OHLCV данными
            config: конфигурация стратегии
            
        Returns:
            dict с сигналами и значениями индикаторов
        """
        # Получаем параметры
        bb_period = config.get('bb_period', 20)
        bb_std = config.get('bb_std', 2)
        atr_period = config.get('atr_period', 14)
        
        # Вычисляем индикаторы (БЕЗ кэширования для корректной работы в бэктесте)
        bb_upper, bb_middle, bb_lower = self.indicators.calculate_bollinger_bands(
            data['close'], bb_period, bb_std, cache_key=None
        )
        atr = self.indicators.calculate_atr(
            data['high'], data['low'], data['close'], atr_period, cache_key=None
        )
        
        # Получаем текущие значения (используем -1 для последнего элемента)
        if (len(data) == 0 or len(bb_upper) == 0 or len(bb_lower) == 0 or len(atr) == 0):
            return {
                'long_signal': False,
                'short_signal': False,
                'touching_lower': False,
                'touching_upper': False,
                'low_volatility': False,
                'indicators': {
                    'bb_upper': 0,
                    'bb_middle': 0,
                    'bb_lower': 0,
                    'atr': 0,
                    'avg_atr': 0,
                    'bb_upper_series': bb_upper,
                    'bb_middle_series': bb_middle,
                    'bb_lower_series': bb_lower,
                    'atr_series': atr
                }
            }

        # Проверяем, что у нас достаточно данных
        if (pd.isna(bb_upper.iloc[-1]) or
            pd.isna(bb_lower.iloc[-1]) or
            pd.isna(atr.iloc[-1])):
            return {
                'long_signal': False,
                'short_signal': False,
                'touching_lower': False,
                'touching_upper': False,
                'low_volatility': False,
                'indicators': {
                    'bb_upper': 0,
                    'bb_middle': 0,
                    'bb_lower': 0,
                    'atr': 0,
                    'avg_atr': 0,
                    'bb_upper_series': bb_upper,
                    'bb_middle_series': bb_middle,
                    'bb_lower_series': bb_lower,
                    'atr_series': atr
                }
            }

        current_price = data['close'].iloc[-1]
        bb_upper_current = bb_upper.iloc[-1]
        bb_lower_current = bb_lower.iloc[-1]
        atr_current = atr.iloc[-1]
        
        # Проверяем касание полос
        touching_lower = current_price <= bb_lower_current * 1.01  # 1% допуск
        touching_upper = current_price >= bb_upper_current * 0.99  # 1% допуск
        
        # Проверяем низкую волатильность (ATR ниже среднего)
        avg_atr = atr.tail(20).mean()
        low_volatility = atr_current < avg_atr * 0.8
        
        # Определяем сигналы
        long_signal = touching_lower and low_volatility
        short_signal = touching_upper and low_volatility
        
        return {
            'long_signal': long_signal,
            'short_signal': short_signal,
            'touching_lower': touching_lower,
            'touching_upper': touching_upper,
            'low_volatility': low_volatility,
            'indicators': {
                'bb_upper': bb_upper_current,
                'bb_middle': bb_middle.iloc[-1],
                'bb_lower': bb_lower_current,
                'atr': atr_current,
                'avg_atr': avg_atr,
                'bb_upper_series': bb_upper,
                'bb_middle_series': bb_middle,
                'bb_lower_series': bb_lower,
                'atr_series': atr
            }
        }
    
    def momentum_trend_signal(self, data: pd.DataFrame, config: dict) -> dict:
        """
        Стратегия: Моментум + трендовый фильтр (SuperTrend + Stochastic RSI)
        
        Args:
            data: DataFrame с OHLCV данными
            config: конфигурация стратегии
            
        Returns:
            dict с сигналами и значениями индикаторов
        """
        # Получаем параметры
        st_period = config.get('supertrend_period', 10)
        st_mult = config.get('supertrend_multiplier', 3)
        stoch_k = config.get('stoch_rsi_k', 14)
        stoch_d = config.get('stoch_rsi_d', 3)
        stoch_oversold_level = config.get('stoch_oversold_level', 20)
        stoch_overbought_level = config.get('stoch_overbought_level', 80)

        # Вычисляем индикаторы (БЕЗ кэширования для корректной работы в бэктесте)
        supertrend, direction = self.indicators.calculate_supertrend(
            data['high'], data['low'], data['close'], st_period, st_mult,
            cache_key=None
        )

        stoch_k_percent, stoch_d_percent = self.indicators.calculate_stochastic_rsi(
            data['close'], stoch_k, stoch_d, 14, cache_key=None
        )
        
        # Получаем текущие значения (используем -1 для последнего элемента)
        if (len(data) == 0 or len(direction) == 0 or len(stoch_k_percent) == 0 or len(stoch_d_percent) == 0):
            return {
                'long_signal': False,
                'short_signal': False,
                'trend_up': False,
                'trend_down': False,
                'stoch_oversold': False,
                'stoch_overbought': False,
                'indicators': {
                    'supertrend': 0,
                    'direction': 0,
                    'stoch_k': 0,
                    'stoch_d': 0,
                    'supertrend_series': supertrend,
                    'direction_series': direction,
                    'stoch_k_series': stoch_k_percent,
                    'stoch_d_series': stoch_d_percent
                }
            }

        # Проверяем, что у нас достаточно данных
        if (pd.isna(direction.iloc[-1]) or
            pd.isna(stoch_k_percent.iloc[-1]) or
            pd.isna(stoch_d_percent.iloc[-1])):
            return {
                'long_signal': False,
                'short_signal': False,
                'trend_up': False,
                'trend_down': False,
                'stoch_oversold': False,
                'stoch_overbought': False,
                'indicators': {
                    'supertrend': 0,
                    'direction': 0,
                    'stoch_k': 0,
                    'stoch_d': 0,
                    'supertrend_series': supertrend,
                    'direction_series': direction,
                    'stoch_k_series': stoch_k_percent,
                    'stoch_d_series': stoch_d_percent
                }
            }

        direction_current = direction.iloc[-1]
        stoch_k_current = stoch_k_percent.iloc[-1]
        stoch_d_current = stoch_d_percent.iloc[-1]

        # Проверяем направление SuperTrend
        trend_up = direction_current == 1
        trend_down = direction_current == -1

        # Проверяем Stochastic RSI (используем настройки из конфига)
        stoch_oversold = stoch_k_current < stoch_oversold_level
        stoch_overbought = stoch_k_current > stoch_overbought_level

        # Определяем сигналы
        long_signal = trend_up and stoch_oversold
        short_signal = trend_down and stoch_overbought
        
        return {
            'long_signal': long_signal,
            'short_signal': short_signal,
            'trend_up': trend_up,
            'trend_down': trend_down,
            'stoch_oversold': stoch_oversold,
            'stoch_overbought': stoch_overbought,
            'indicators': {
                'supertrend': supertrend.iloc[-1],
                'direction': direction_current,
                'stoch_k': stoch_k_current,
                'stoch_d': stoch_d_current,
                'supertrend_series': supertrend,
                'direction_series': direction,
                'stoch_k_series': stoch_k_percent,
                'stoch_d_series': stoch_d_percent
            }
        }

    def mrc_reversion_signal(self, data: pd.DataFrame, config: dict) -> dict:
        """
        Стратегия: MRC (Mean Reversion Channel) — вход при касании заданной
        полосы канала (entry_band). Перенос BTC-бота на 15m, работающего
        живой торговлей больше года (см. algoTrading/mrc_btc_15m_overbought_oversold.txt
        для полной формулы). Live-бот использует entry_band=2 по умолчанию.

        Args:
            data: DataFrame с OHLCV данными
            config: конфигурация — length, inner_mult, outer_mult, gradsize,
                    entry_band (1/2/3), source ('hlc3'|'close'|'ohlc4')

        Returns:
            dict с сигналами и значениями индикатора
        """
        length = config.get('length', 200)
        inner_mult = config.get('inner_mult', 1.0)
        outer_mult = config.get('outer_mult', 2.415)
        gradsize = config.get('gradsize', 0.5)
        entry_band = config.get('entry_band', 2)
        source = config.get('source', 'hlc3')

        safe_return = {
            'long_signal': False,
            'short_signal': False,
            'risk_zone': 0,
            'indicators': {
                'meanline': 0, 'meanrange': 0, 'upband2': 0, 'loband2': 0, 'risk_zone': 0,
            }
        }

        # length-based guard: SuperSmoother математически никогда не даёт NaN
        # после бара 0 (см. calculate_mrc/_supersmoother) — в отличие от
        # остальных indicator-методов этого файла, здесь достаточно длины
        # истории, а не pd.isna() проверки, чтобы решить "прогрелся ли канал".
        if len(data) == 0 or len(data) < length:
            return safe_return

        mrc = self.indicators.calculate_mrc(
            data, length=length, inner_mult=inner_mult, outer_mult=outer_mult,
            gradsize=gradsize, source=source, cache_key=None
        )

        if len(mrc) == 0:
            return safe_return

        risk_zone_current = int(mrc['risk_zone'].iloc[-1])

        long_signal = (risk_zone_current == -entry_band)
        short_signal = (risk_zone_current == entry_band)

        return {
            'long_signal': long_signal,
            'short_signal': short_signal,
            'risk_zone': risk_zone_current,
            'indicators': {
                'meanline': mrc['meanline'].iloc[-1],
                'meanrange': mrc['meanrange'].iloc[-1],
                'upband2': mrc['upband2'].iloc[-1],
                'loband2': mrc['loband2'].iloc[-1],
                'risk_zone': risk_zone_current,
                'meanline_series': mrc['meanline'],
                'risk_zone_series': mrc['risk_zone'],
            }
        }

    def mrc_trend_filtered_signal(self, data: pd.DataFrame, config: dict, trend_data: pd.DataFrame) -> dict:
        """
        Стратегия: MRC вход (1H) отфильтрованный трендом на старшем ТФ (4H EMA).

        Гипотеза: цена находится НАД EMA на трендовом ТФ (структурный uptrend) —
        входим в LONG только когда 1H MRC коснулся band 1 или band 2 oversold
        (перепроданность внутри восходящего тренда, а не разворот тренда).
        Зеркально для SHORT: цена ПОД EMA + MRC band 1/2 overbought.

        В отличие от mrc_reversion_signal (одна полоса entry_band), здесь
        считаем МЕНЕЕ строгим условие "band 1 ИЛИ band 2" через abs(risk_zone),
        т.к. цель — не поймать точный экстремум, а войти по тренду на любом
        заметном отклонении от средней (см. risk_zone кодировку в calculate_mrc:
        1=light, 2=medium, 3=extreme overbought/oversold, 4=near mean, 5=extreme дальше band2_1).

        Args:
            data: DataFrame OHLCV трейдингового (MRC) таймфрейма, напр. 1H
            config: конфигурация — mrc-параметры (length, inner_mult, outer_mult,
                    gradsize, source) + trend_ema_period (EMA период на trend_data)
            trend_data: DataFrame OHLCV трендового таймфрейма, напр. 4H —
                    ПОСЛЕДНЯЯ строка должна быть последней ЗАКРЫТОЙ свечой
                    (защиту от look-ahead bias обеспечивает вызывающий код —
                    backtester.py находит parent-свечу через get_parent_candle_index)

        Returns:
            dict с сигналами и значениями индикаторов (MRC + trend EMA)
        """
        length = config.get('length', 200)
        inner_mult = config.get('inner_mult', 1.0)
        outer_mult = config.get('outer_mult', 2.415)
        gradsize = config.get('gradsize', 0.5)
        entry_bands = config.get('entry_band', [1, 2])
        if isinstance(entry_bands, int):
            entry_bands = [entry_bands]
        source = config.get('source', 'hlc3')
        trend_ema_period = config.get('trend_ema_period', 21)

        safe_return = {
            'long_signal': False,
            'short_signal': False,
            'risk_zone': 0,
            'trend_up': False,
            'trend_down': False,
            'indicators': {
                'meanline': 0, 'meanrange': 0, 'upband2': 0, 'loband2': 0, 'risk_zone': 0,
                'trend_ema': 0, 'trend_price': 0,
            }
        }

        if len(data) == 0 or len(data) < length:
            return safe_return
        if trend_data is None or len(trend_data) < trend_ema_period:
            return safe_return

        trend_ema = self.indicators.calculate_ema(trend_data['close'], trend_ema_period, cache_key=None)
        if len(trend_ema) == 0 or pd.isna(trend_ema.iloc[-1]):
            return safe_return

        trend_ema_current = trend_ema.iloc[-1]
        trend_price_current = trend_data['close'].iloc[-1]
        trend_up = trend_price_current > trend_ema_current
        trend_down = trend_price_current < trend_ema_current

        mrc = self.indicators.calculate_mrc(
            data, length=length, inner_mult=inner_mult, outer_mult=outer_mult,
            gradsize=gradsize, source=source, cache_key=None
        )
        if len(mrc) == 0:
            return safe_return

        risk_zone_current = int(mrc['risk_zone'].iloc[-1])

        # LONG: тренд вверх (4H) + MRC оversold band 1 или 2 (risk_zone отрицательный)
        long_signal = trend_up and (-risk_zone_current in entry_bands)
        # SHORT: тренд вниз (4H) + MRC overbought band 1 или 2 (risk_zone положительный)
        short_signal = trend_down and (risk_zone_current in entry_bands)

        return {
            'long_signal': long_signal,
            'short_signal': short_signal,
            'risk_zone': risk_zone_current,
            'trend_up': trend_up,
            'trend_down': trend_down,
            'indicators': {
                'meanline': mrc['meanline'].iloc[-1],
                'meanrange': mrc['meanrange'].iloc[-1],
                'upband2': mrc['upband2'].iloc[-1],
                'loband2': mrc['loband2'].iloc[-1],
                'risk_zone': risk_zone_current,
                'trend_ema': trend_ema_current,
                'trend_price': trend_price_current,
                'meanline_series': mrc['meanline'],
                'risk_zone_series': mrc['risk_zone'],
            }
        }

    def custom_signal(self, data: pd.DataFrame, config: dict) -> dict:
        """
        Кастомная стратегия с возможностью выбора любой комбинации индикаторов

        Args:
            data: DataFrame с OHLCV данными
            config: конфигурация с выбранными индикаторами

        Returns:
            dict с сигналами и значениями индикаторов
        """
        selected = config.get('selected_indicators', {})
        result = {
            'long_signal': False,
            'short_signal': False,
            'indicators': {}
        }

        # Если ничего не выбрано, возвращаем пустой результат
        if not any(selected.values()):
            return result

        # Список условий для long и short сигналов
        long_conditions = []
        short_conditions = []

        # EMA - трендовый фильтр
        if selected.get('ema', False):
            ema_config = config.get('ema', {})

            # Поддержка двух режимов: сравнение двух EMA или цены с одной EMA
            use_price_comparison = ema_config.get('use_price_comparison', False)

            if use_price_comparison:
                # Режим: price vs EMA
                ema_period = ema_config.get('period', 200)
                ema = self.indicators.calculate_ema(data['close'], ema_period, cache_key=None)

                if len(ema) > 0 and not pd.isna(ema.iloc[-1]):
                    current_price = data['close'].iloc[-1]
                    ema_value = ema.iloc[-1]

                    # Для LONG: цена выше EMA, для SHORT: цена ниже EMA
                    price_above_ema = current_price > ema_value
                    price_below_ema = current_price < ema_value

                    long_conditions.append(price_above_ema)
                    short_conditions.append(price_below_ema)

                    result['indicators']['ema'] = ema_value
                    result['indicators']['price'] = current_price
            else:
                # Режим: EMA short vs EMA long (старая логика)
                ema_short_period = ema_config.get('short_period', 50)
                ema_long_period = ema_config.get('long_period', 200)

                ema_short = self.indicators.calculate_ema(data['close'], ema_short_period, cache_key=None)
                ema_long = self.indicators.calculate_ema(data['close'], ema_long_period, cache_key=None)

                if len(ema_short) > 0 and len(ema_long) > 0 and not pd.isna(ema_short.iloc[-1]) and not pd.isna(ema_long.iloc[-1]):
                    trend_up = ema_short.iloc[-1] > ema_long.iloc[-1]
                    trend_down = ema_short.iloc[-1] < ema_long.iloc[-1]

                    long_conditions.append(trend_up)
                    short_conditions.append(trend_down)

                    result['indicators']['ema_short'] = ema_short.iloc[-1]
                    result['indicators']['ema_long'] = ema_long.iloc[-1]

        # RSI - моментум индикатор
        if selected.get('rsi', False):
            rsi_config = config.get('rsi', {})
            rsi_period = rsi_config.get('period', 14)
            rsi_oversold = rsi_config.get('oversold', 30)
            rsi_overbought = rsi_config.get('overbought', 70)

            # Поддержка crossover detection
            use_crossover = rsi_config.get('use_crossover', False)
            crossover_level_long = rsi_config.get('crossover_level_long', 38)
            crossover_level_short = rsi_config.get('crossover_level_short', 62)

            rsi = self.indicators.calculate_rsi(data['close'], rsi_period, cache_key=None)

            if len(rsi) > 0 and not pd.isna(rsi.iloc[-1]):
                rsi_current = rsi.iloc[-1]

                if use_crossover:
                    # Режим crossover: RSI пересекает уровень
                    # Для LONG: RSI[-2] < level и RSI[-1] >= level (пересечение вверх)
                    # Для SHORT: RSI[-2] > level и RSI[-1] <= level (пересечение вниз)

                    if len(rsi) >= 2 and not pd.isna(rsi.iloc[-2]):
                        rsi_prev = rsi.iloc[-2]

                        # LONG: RSI был <= level, теперь выше (пересечение вверх)
                        rsi_cross_up = (rsi_prev <= crossover_level_long) and (rsi_current > crossover_level_long)

                        # SHORT: RSI был >= level, теперь ниже (пересечение вниз)
                        rsi_cross_down = (rsi_prev >= crossover_level_short) and (rsi_current < crossover_level_short)

                        # Дополнительное условие: RSI должен быть в зоне
                        rsi_in_long_zone = rsi_current <= crossover_level_long + 10  # Небольшой допуск
                        rsi_in_short_zone = rsi_current >= crossover_level_short - 10

                        long_conditions.append(rsi_cross_up and rsi_in_long_zone)
                        short_conditions.append(rsi_cross_down and rsi_in_short_zone)

                        result['indicators']['rsi'] = rsi_current
                        result['indicators']['rsi_prev'] = rsi_prev
                        result['indicators']['rsi_cross_up'] = rsi_cross_up
                        result['indicators']['rsi_cross_down'] = rsi_cross_down
                    else:
                        # Недостаточно данных для crossover
                        long_conditions.append(False)
                        short_conditions.append(False)
                        result['indicators']['rsi'] = rsi_current
                else:
                    # Режим обычной проверки уровня (старая логика)
                    long_conditions.append(rsi_current < rsi_oversold)
                    short_conditions.append(rsi_current > rsi_overbought)
                    result['indicators']['rsi'] = rsi_current

        # Bollinger Bands - волатильность
        if selected.get('bollinger_bands', False):
            bb_config = config.get('bollinger_bands', {})
            bb_period = bb_config.get('period', 20)
            bb_std = bb_config.get('std_dev', 2)

            bb_upper, bb_middle, bb_lower = self.indicators.calculate_bollinger_bands(
                data['close'], bb_period, bb_std, cache_key=None
            )

            if len(bb_lower) > 0 and len(bb_upper) > 0 and not pd.isna(bb_lower.iloc[-1]) and not pd.isna(bb_upper.iloc[-1]):
                current_price = data['close'].iloc[-1]

                # Касание нижней/верхней полосы
                touching_lower = current_price <= bb_lower.iloc[-1] * 1.01
                touching_upper = current_price >= bb_upper.iloc[-1] * 0.99

                long_conditions.append(touching_lower)
                short_conditions.append(touching_upper)

                result['indicators']['bb_upper'] = bb_upper.iloc[-1]
                result['indicators']['bb_middle'] = bb_middle.iloc[-1]
                result['indicators']['bb_lower'] = bb_lower.iloc[-1]

        # ATR - дополнительный фильтр волатильности
        if selected.get('atr', False):
            atr_config = config.get('atr', {})
            atr_period = atr_config.get('period', 14)

            atr = self.indicators.calculate_atr(
                data['high'], data['low'], data['close'], atr_period, cache_key=None
            )

            if len(atr) > 0 and not pd.isna(atr.iloc[-1]):
                atr_current = atr.iloc[-1]
                avg_atr = atr.tail(20).mean() if len(atr) >= 20 else atr_current

                # Низкая волатильность - хорошо для входа
                low_volatility = atr_current < avg_atr * 0.8

                # ATR сам по себе не генерирует сигналы, только фильтрует
                if low_volatility:
                    # Не добавляем условие, но сохраняем информацию
                    pass

                result['indicators']['atr'] = atr_current
                result['indicators']['avg_atr'] = avg_atr

        # SuperTrend - трендовый индикатор
        if selected.get('supertrend', False):
            st_config = config.get('supertrend', {})
            st_period = st_config.get('period', 10)
            st_mult = st_config.get('multiplier', 3)

            supertrend, direction = self.indicators.calculate_supertrend(
                data['high'], data['low'], data['close'], st_period, st_mult, cache_key=None
            )

            if len(direction) > 0 and not pd.isna(direction.iloc[-1]):
                trend_up = direction.iloc[-1] == 1
                trend_down = direction.iloc[-1] == -1

                long_conditions.append(trend_up)
                short_conditions.append(trend_down)

                result['indicators']['supertrend'] = supertrend.iloc[-1]
                result['indicators']['direction'] = direction.iloc[-1]

        # Stochastic RSI - моментум индикатор
        if selected.get('stochastic_rsi', False):
            stoch_config = config.get('stochastic_rsi', {})
            stoch_k = stoch_config.get('k_period', 14)
            stoch_d = stoch_config.get('d_period', 3)
            stoch_rsi_period = stoch_config.get('rsi_period', 14)
            stoch_oversold_level = stoch_config.get('oversold_level', 20)
            stoch_overbought_level = stoch_config.get('overbought_level', 80)

            stoch_k_percent, stoch_d_percent = self.indicators.calculate_stochastic_rsi(
                data['close'], stoch_k, stoch_d, stoch_rsi_period, cache_key=None
            )

            if len(stoch_k_percent) > 0 and not pd.isna(stoch_k_percent.iloc[-1]):
                stoch_oversold = stoch_k_percent.iloc[-1] < stoch_oversold_level
                stoch_overbought = stoch_k_percent.iloc[-1] > stoch_overbought_level

                long_conditions.append(stoch_oversold)
                short_conditions.append(stoch_overbought)

                result['indicators']['stoch_k'] = stoch_k_percent.iloc[-1]
                result['indicators']['stoch_d'] = stoch_d_percent.iloc[-1]

        # ADX - индикатор силы тренда
        if selected.get('adx', False):
            adx_config = config.get('adx', {})
            adx_period = adx_config.get('period', 14)
            adx_max_value = adx_config.get('max_value', 25)  # ADX <= 25 означает слабый тренд/флет

            adx = self.indicators.calculate_adx(
                data['high'], data['low'], data['close'], adx_period, cache_key=None
            )

            if len(adx) > 0 and not pd.isna(adx.iloc[-1]):
                adx_current = adx.iloc[-1]

                # ADX используется как фильтр: низкий ADX (слабый тренд) хорош для mean reversion
                # высокий ADX (сильный тренд) хорош для trend following
                # Для стратегии пользователя: ADX <= max_value (например 25)
                adx_below_threshold = adx_current <= adx_max_value

                # ADX не генерирует сигналы сам по себе, он фильтрует
                # Добавляем условие для обоих направлений
                long_conditions.append(adx_below_threshold)
                short_conditions.append(adx_below_threshold)

                result['indicators']['adx'] = adx_current
                result['indicators']['adx_threshold'] = adx_max_value

        # Определяем финальные сигналы
        # Требуем, чтобы ВСЕ выбранные индикаторы давали согласованный сигнал
        result['long_signal'] = all(long_conditions) if long_conditions else False
        result['short_signal'] = all(short_conditions) if short_conditions else False

        return result
