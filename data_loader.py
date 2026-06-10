import pandas as pd
import numpy as np
from typing import Optional, Union, List
from pathlib import Path
import requests
import json
from datetime import datetime, timedelta
import time

try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False
    print("CCXT не установлен. Загрузка с бирж недоступна.")

class DataLoader:
    """
    Класс для загрузки исторических данных OHLCV
    Поддерживает загрузку из CSV файлов и API (расширяемо)
    """
    
    def __init__(self):
        self.data = None
        self.symbol = None
        self.timeframe = None
    
    def load_from_csv(self, file_path: Union[str, Path], symbol: str = None) -> pd.DataFrame:
        """
        Загружает данные из CSV файла
        
        Args:
            file_path: путь к CSV файлу
            symbol: символ торговой пары
            
        Returns:
            DataFrame с колонками: timestamp, open, high, low, close, volume
        """
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                raise FileNotFoundError(f"Файл {file_path} не найден")
            
            # Загружаем CSV
            df = pd.read_csv(file_path)
            
            # Проверяем наличие обязательных колонок
            required_columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                raise ValueError(f"Отсутствуют обязательные колонки: {missing_columns}")
            
            # Конвертируем timestamp в datetime
            if df['timestamp'].dtype == 'object':
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            elif df['timestamp'].dtype in ['int64', 'float64']:
                # Предполагаем, что это Unix timestamp
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            
            # Сортируем по времени
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            # Проверяем корректность OHLC данных
            invalid_ohlc = df[(df['high'] < df['low']) | 
                             (df['high'] < df['open']) | 
                             (df['high'] < df['close']) |
                             (df['low'] > df['open']) | 
                             (df['low'] > df['close'])]
            
            if not invalid_ohlc.empty:
                print(f"Предупреждение: найдено {len(invalid_ohlc)} строк с некорректными OHLC данными")
            
            self.data = df
            self.symbol = symbol or file_path.stem
            
            print(f"Загружено {len(df)} записей для {self.symbol}")
            print(f"Период: {df['timestamp'].min()} - {df['timestamp'].max()}")
            
            return df
            
        except Exception as e:
            raise Exception(f"Ошибка при загрузке данных: {str(e)}")
    
    def load_from_api(self,
                     symbol: str,
                     timeframe: str,
                     start_date: str = None,
                     end_date: str = None,
                     exchange: str = 'binance',
                     limit: int = 1000,
                     market_type: str = 'spot') -> pd.DataFrame:
        """
        Загружает данные с биржи через CCXT

        Args:
            symbol: торговая пара (например, 'BTC/USDT')
            timeframe: таймфрейм ('1m', '5m', '15m', '1h', '4h', '1d')
            start_date: начальная дата в формате 'YYYY-MM-DD' или 'YYYY-MM-DD HH:MM:SS'
            end_date: конечная дата в формате 'YYYY-MM-DD' или 'YYYY-MM-DD HH:MM:SS'
            exchange: название биржи ('binance', 'okx', 'bybit', 'kucoin', etc.)
            limit: максимальное количество свечей за один запрос
            market_type: тип рынка ('spot', 'futures', 'swap')

        Returns:
            DataFrame с колонками: timestamp, open, high, low, close, volume
        """
        if not CCXT_AVAILABLE:
            raise ImportError("CCXT не установлен. Установите: pip install ccxt")
        
        try:
            # Создаем экземпляр биржи
            exchange_class = getattr(ccxt, exchange.lower())
            exchange_instance = exchange_class({
                'rateLimit': 1200,  # Ограничение запросов
                'enableRateLimit': True,
            })
            
            print(f"Подключение к бирже: {exchange_instance.name}")

            # Проверяем поддержку OHLCV
            if not exchange_instance.has['fetchOHLCV']:
                raise Exception(f"Биржа {exchange} не поддерживает загрузку OHLCV данных")

            # Формируем символ в зависимости от типа рынка
            full_symbol = symbol
            if market_type in ['futures', 'swap']:
                # Для фьючерсов добавляем суффикс :USDT если его нет
                if ':' not in symbol:
                    # Определяем quote currency из символа
                    if '/USDT' in symbol:
                        full_symbol = symbol + ':USDT'
                    elif '/USD' in symbol:
                        full_symbol = symbol + ':USD'
                    elif '/BUSD' in symbol:
                        full_symbol = symbol + ':BUSD'
                    else:
                        full_symbol = symbol + ':USDT'  # По умолчанию USDT

            # Проверяем доступность символа
            markets = exchange_instance.load_markets()
            if full_symbol not in markets:
                # Попробуем найти похожие символы
                similar_symbols = [s for s in markets.keys() if symbol.replace('/', '') in s.replace('/', '').replace(':', '')]
                error_msg = f"Символ {full_symbol} недоступен на {exchange}."
                if similar_symbols:
                    error_msg += f" Похожие символы: {similar_symbols[:5]}"
                else:
                    available_symbols = list(markets.keys())[:10]
                    error_msg += f" Доступные символы (первые 10): {available_symbols}"
                raise Exception(error_msg)

            # Обновляем symbol на полный символ
            symbol = full_symbol
            print(f"Используется символ: {symbol} (тип рынка: {market_type})")
            
            # Проверяем поддержку таймфрейма
            if timeframe not in exchange_instance.timeframes:
                available_timeframes = list(exchange_instance.timeframes.keys())
                raise Exception(f"Таймфрейм {timeframe} не поддерживается на {exchange}. "
                              f"Доступные: {available_timeframes}")
            
            # Конвертируем даты в timestamp
            since = None
            until = None
            
            if start_date:
                since = self._parse_date_to_timestamp(start_date)
            
            if end_date:
                until = self._parse_date_to_timestamp(end_date)
            
            # Загружаем данные
            all_ohlcv = []
            current_since = since
            
            print(f"Загрузка данных {symbol} {timeframe} с {exchange}...")
            
            while True:
                try:
                    # Делаем запрос к бирже
                    ohlcv = exchange_instance.fetch_ohlcv(
                        symbol=symbol,
                        timeframe=timeframe,
                        since=current_since,
                        limit=limit
                    )
                    
                    if not ohlcv:
                        break
                    
                    # Фильтруем по конечной дате если указана
                    if until:
                        ohlcv = [candle for candle in ohlcv if candle[0] <= until]
                    
                    all_ohlcv.extend(ohlcv)
                    
                    # Проверяем, достигли ли конечной даты
                    if until and ohlcv and ohlcv[-1][0] >= until:
                        break
                    
                    # Обновляем timestamp для следующего запроса
                    if ohlcv:
                        current_since = ohlcv[-1][0] + 1
                    else:
                        break
                    
                    # Показываем прогресс
                    if len(all_ohlcv) % 5000 == 0:
                        last_date = datetime.fromtimestamp(ohlcv[-1][0] / 1000)
                        print(f"Загружено {len(all_ohlcv)} свечей, последняя дата: {last_date}")
                    
                    # Пауза между запросами для соблюдения лимитов
                    time.sleep(exchange_instance.rateLimit / 1000)
                    
                except ccxt.BaseError as e:
                    print(f"Ошибка при загрузке данных: {e}")
                    time.sleep(5)  # Пауза при ошибке
                    continue
            
            if not all_ohlcv:
                raise Exception("Не удалось загрузить данные")
            
            # Конвертируем в DataFrame
            df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Конвертируем timestamp в datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            # Удаляем дубликаты и сортируем
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            
            # Сохраняем информацию
            self.data = df
            self.symbol = symbol.replace('/', '')  # BTC/USDT -> BTCUSDT
            self.timeframe = timeframe
            
            print(f"Загружено {len(df)} записей для {symbol}")
            print(f"Период: {df['timestamp'].min()} - {df['timestamp'].max()}")
            
            return df
            
        except Exception as e:
            raise Exception(f"Ошибка при загрузке данных с {exchange}: {str(e)}")
    
    def _parse_date_to_timestamp(self, date_str: str) -> int:
        """Конвертирует строку даты в timestamp (миллисекунды)"""
        try:
            # Пробуем разные форматы
            formats = [
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%d %H:%M',
                '%Y-%m-%d',
                '%d.%m.%Y %H:%M:%S',
                '%d.%m.%Y %H:%M',
                '%d.%m.%Y'
            ]
            
            for fmt in formats:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    return int(dt.timestamp() * 1000)
                except ValueError:
                    continue
            
            raise ValueError(f"Неподдерживаемый формат даты: {date_str}")
            
        except Exception as e:
            raise ValueError(f"Ошибка парсинга даты '{date_str}': {str(e)}")
    
    def get_available_exchanges(self) -> List[str]:
        """Возвращает список доступных бирж"""
        if not CCXT_AVAILABLE:
            return []
        
        # Фильтруем только биржи с поддержкой OHLCV
        exchanges = []
        for exchange_id in ccxt.exchanges:
            try:
                exchange_class = getattr(ccxt, exchange_id)
                if hasattr(exchange_class, 'has') and exchange_class.has.get('fetchOHLCV', False):
                    exchanges.append(exchange_id)
            except:
                continue
        
        return sorted(exchanges)
    
    def get_exchange_info(self, exchange: str) -> dict:
        """Получает информацию о бирже"""
        if not CCXT_AVAILABLE:
            return {}
        
        try:
            exchange_class = getattr(ccxt, exchange.lower())
            exchange_instance = exchange_class()
            
            markets = exchange_instance.load_markets()
            
            return {
                'name': exchange_instance.name,
                'countries': getattr(exchange_instance, 'countries', []),
                'has_ohlcv': exchange_instance.has.get('fetchOHLCV', False),
                'timeframes': list(exchange_instance.timeframes.keys()) if hasattr(exchange_instance, 'timeframes') else [],
                'symbols_count': len(markets),
                'rate_limit': exchange_instance.rateLimit,
                'popular_symbols': [s for s in ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'ADA/USDT', 'SOL/USDT'] if s in markets]
            }
            
        except Exception as e:
            return {'error': str(e)}
    
    def save_to_csv(self, filename: str = None, data: pd.DataFrame = None) -> str:
        """
        Сохраняет загруженные данные в CSV файл
        
        Args:
            filename: имя файла (если не указано, генерируется автоматически)
            data: данные для сохранения (если не указаны, используются загруженные)
            
        Returns:
            Путь к сохраненному файлу
        """
        df = data if data is not None else self.data
        
        if df is None:
            raise ValueError("Нет данных для сохранения")
        
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            symbol = self.symbol or "data"
            timeframe = self.timeframe or "unknown"
            filename = f"data/{symbol}_{timeframe}_{timestamp}.csv"
        
        # Создаем директорию если не существует
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        
        # Сохраняем
        df.to_csv(filename, index=False)
        
        print(f"Данные сохранены в {filename}")
        return filename
    
    def filter_by_date(self, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """
        Фильтрует данные по датам
        
        Args:
            start_date: начальная дата в формате 'YYYY-MM-DD'
            end_date: конечная дата в формате 'YYYY-MM-DD'
            
        Returns:
            Отфильтрованный DataFrame
        """
        if self.data is None:
            raise ValueError("Данные не загружены")
        
        df = self.data.copy()
        
        if start_date:
            start_date = pd.to_datetime(start_date)
            df = df[df['timestamp'] >= start_date]
        
        if end_date:
            end_date = pd.to_datetime(end_date)
            df = df[df['timestamp'] <= end_date]
        
        return df
    
    def get_price_at_timestamp(self, timestamp: pd.Timestamp, price_type: str = 'close') -> float:
        """
        Получает цену на определенный момент времени
        
        Args:
            timestamp: временная метка
            price_type: тип цены ('open', 'high', 'low', 'close')
            
        Returns:
            Цена
        """
        if self.data is None:
            raise ValueError("Данные не загружены")
        
        # Находим ближайшую временную метку
        idx = self.data['timestamp'].searchsorted(timestamp)
        
        if idx >= len(self.data):
            idx = len(self.data) - 1
        elif idx > 0 and abs(self.data.iloc[idx-1]['timestamp'] - timestamp) < abs(self.data.iloc[idx]['timestamp'] - timestamp):
            idx = idx - 1
        
        return self.data.iloc[idx][price_type]
    
    def validate_data(self) -> dict:
        """
        Проверяет качество загруженных данных
        
        Returns:
            Словарь с результатами проверки
        """
        if self.data is None:
            raise ValueError("Данные не загружены")
        
        df = self.data
        
        validation_results = {
            'total_records': len(df),
            'missing_values': df.isnull().sum().to_dict(),
            'duplicate_timestamps': df['timestamp'].duplicated().sum(),
            'data_gaps': [],
            'price_anomalies': 0
        }
        
        # Проверяем пропуски во времени
        time_diffs = df['timestamp'].diff().dropna()
        if len(time_diffs) > 1:
            median_diff = time_diffs.median()
            large_gaps = time_diffs[time_diffs > median_diff * 2]
            validation_results['data_gaps'] = len(large_gaps)
        
        # Проверяем аномалии в ценах (резкие скачки > 50%)
        price_changes = df['close'].pct_change().abs()
        validation_results['price_anomalies'] = (price_changes > 0.5).sum()
        
        return validation_results
    
    def resample_to_timeframe(self, data: pd.DataFrame, target_timeframe: str) -> pd.DataFrame:
        """
        Ресемплирует данные в целевой таймфрейм

        Args:
            data: DataFrame с OHLCV данными
            target_timeframe: целевой таймфрейм ('5m', '15m', '1h', etc.)

        Returns:
            DataFrame с ресемплированными данными
        """
        # Конвертируем таймфрейм в pandas offset
        timeframe_map = {
            '1m': '1T',
            '3m': '3T',
            '5m': '5T',
            '15m': '15T',
            '30m': '30T',
            '1h': '1H',
            '2h': '2H',
            '4h': '4H',
            '6h': '6H',
            '8h': '8H',
            '12h': '12H',
            '1d': '1D',
            '3d': '3D',
            '1w': '1W',
            '1M': '1M'
        }

        if target_timeframe not in timeframe_map:
            raise ValueError(f"Неподдерживаемый таймфрейм: {target_timeframe}")

        offset = timeframe_map[target_timeframe]

        # Устанавливаем timestamp как индекс
        # label='left' - метка времени на начале периода (timestamp = время открытия свечи)
        # closed='left' - включает левую границу периода [start, end)
        # Это стандартное поведение для финансовых OHLCV данных
        df_resampled = data.set_index('timestamp').resample(
            offset,
            label='left',   # Метка на начале периода
            closed='left'   # Включая левую границу [start, end)
        ).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna().reset_index()

        return df_resampled

    def get_parent_candle_index(self, execution_timestamp: pd.Timestamp,
                               data_strategy_tf: pd.DataFrame,
                               strategy_timeframe: str) -> int:
        """
        Находит индекс последней ЗАКРЫТОЙ свечи стратегического таймфрейма
        для данного execution тика (избегает look-ahead bias)

        ВАЖНО: В OHLCV данных timestamp означает время ОТКРЫТИЯ свечи.
        Свеча полностью закрывается в момент (timestamp + timeframe_duration).
        Эта функция гарантирует что используются только ПОЛНОСТЬЮ ЗАКРЫТЫЕ свечи.

        Пример (15m timeframe):
        - Свеча с timestamp=10:00 означает период [10:00 - 10:15)
        - Свеча закрывается в момент 10:15
        - Для execution тика 10:05 последняя закрытая свеча - это 09:45 (не 10:00!)
        - Для execution тика 10:15 последняя закрытая свеча - это 10:00

        Args:
            execution_timestamp: timestamp execution тика
            data_strategy_tf: DataFrame стратегического таймфрейма (15m, 1h, etc.)
            strategy_timeframe: таймфрейм стратегии ('15m', '1h', etc.)

        Returns:
            Индекс родительской свечи в data_strategy_tf, -1 если нет закрытых свечей
        """
        # Конвертируем таймфрейм в timedelta для расчета времени закрытия
        timeframe_delta = self._timeframe_to_timedelta(strategy_timeframe)

        # Создаем копию для безопасности
        df_temp = data_strategy_tf.copy()

        # Вычисляем время закрытия каждой свечи
        # Свеча с timestamp T закрывается в момент T + timeframe_delta
        df_temp['close_time'] = df_temp['timestamp'] + timeframe_delta

        # Находим все свечи которые ПОЛНОСТЬЮ ЗАКРЫЛИСЬ до execution_timestamp
        # Свеча считается закрытой если close_time <= execution_timestamp
        closed_candles = df_temp[df_temp['close_time'] <= execution_timestamp]

        if closed_candles.empty:
            return -1  # Нет закрытых свечей

        # Возвращаем индекс последней закрытой свечи
        return closed_candles.index[-1]

    def _timeframe_to_timedelta(self, timeframe: str) -> pd.Timedelta:
        """
        Конвертирует строку таймфрейма в pandas Timedelta

        Args:
            timeframe: строка таймфрейма ('1m', '5m', '15m', '1h', etc.)

        Returns:
            pd.Timedelta объект

        Raises:
            ValueError: если таймфрейм не поддерживается
        """
        timeframe_map = {
            '1m': pd.Timedelta(minutes=1),
            '3m': pd.Timedelta(minutes=3),
            '5m': pd.Timedelta(minutes=5),
            '15m': pd.Timedelta(minutes=15),
            '30m': pd.Timedelta(minutes=30),
            '1h': pd.Timedelta(hours=1),
            '2h': pd.Timedelta(hours=2),
            '4h': pd.Timedelta(hours=4),
            '6h': pd.Timedelta(hours=6),
            '8h': pd.Timedelta(hours=8),
            '12h': pd.Timedelta(hours=12),
            '1d': pd.Timedelta(days=1),
            '3d': pd.Timedelta(days=3),
            '1w': pd.Timedelta(weeks=1),
            '1M': pd.Timedelta(days=30)  # Приблизительно 30 дней
        }

        if timeframe not in timeframe_map:
            raise ValueError(f"Неподдерживаемый таймфрейм: {timeframe}. "
                           f"Доступные: {list(timeframe_map.keys())}")

        return timeframe_map[timeframe]

    def load_dual_timeframe(self,
                           symbol: str,
                           strategy_timeframe: str,
                           execution_timeframe: str,
                           start_date: str = None,
                           end_date: str = None,
                           exchange: str = 'binance',
                           market_type: str = 'spot') -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Загружает данные для multi-timeframe бэктестинга

        Args:
            symbol: торговая пара (например, 'BTC/USDT')
            strategy_timeframe: таймфрейм для индикаторов ('15m', '1h', etc.)
            execution_timeframe: таймфрейм для исполнения ('1m', '5m')
            start_date: начальная дата
            end_date: конечная дата
            exchange: название биржи
            market_type: тип рынка ('spot', 'futures', 'swap')

        Returns:
            Tuple (execution_data, strategy_data):
                - execution_data: DataFrame с данными execution таймфрейма
                - strategy_data: DataFrame с данными strategy таймфрейма
        """
        print(f"\n{'='*60}")
        print(f"ЗАГРУЗКА DUAL TIMEFRAME ДАННЫХ")
        print(f"{'='*60}")
        print(f"Exchange: {exchange}")
        print(f"Символ: {symbol}")
        print(f"Execution TF: {execution_timeframe}")
        print(f"Strategy TF: {strategy_timeframe}")
        print(f"Период: {start_date} - {end_date}")
        print(f"{'='*60}\n")

        # Загружаем данные execution таймфрейма (самый мелкий)
        execution_data = self.load_from_api(
            symbol=symbol,
            timeframe=execution_timeframe,
            start_date=start_date,
            end_date=end_date,
            exchange=exchange,
            market_type=market_type
        )

        print(f"\n{'='*60}")
        print(f"РЕСЕМПЛИНГ В STRATEGY TIMEFRAME")
        print(f"{'='*60}")

        # Ресемплируем в strategy таймфрейм
        strategy_data = self.resample_to_timeframe(execution_data, strategy_timeframe)

        print(f"Execution данные ({execution_timeframe}): {len(execution_data)} свечей")
        print(f"Strategy данные ({strategy_timeframe}): {len(strategy_data)} свечей")
        print(f"Соотношение: {len(execution_data) / len(strategy_data):.1f}:1")
        print(f"{'='*60}\n")

        return execution_data, strategy_data

    def get_summary(self) -> dict:
        """
        Возвращает сводную информацию о данных
        """
        if self.data is None:
            raise ValueError("Данные не загружены")

        df = self.data

        return {
            'symbol': self.symbol,
            'records_count': len(df),
            'date_range': {
                'start': df['timestamp'].min().strftime('%Y-%m-%d %H:%M:%S'),
                'end': df['timestamp'].max().strftime('%Y-%m-%d %H:%M:%S')
            },
            'price_range': {
                'min': df['low'].min(),
                'max': df['high'].max(),
                'first_close': df['close'].iloc[0],
                'last_close': df['close'].iloc[-1]
            },
            'volume_stats': {
                'total': df['volume'].sum(),
                'average': df['volume'].mean(),
                'max': df['volume'].max()
            }
        } 