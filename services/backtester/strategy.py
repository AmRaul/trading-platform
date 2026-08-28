import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

# Импортируем модуль индикаторов
try:
    from indicators import TechnicalIndicators, IndicatorStrategy
    INDICATORS_AVAILABLE = True
except ImportError:
    INDICATORS_AVAILABLE = False
    print("Warning: indicators module not available. Technical indicators will be disabled.")

class OrderType(Enum):
    LONG = "long"
    SHORT = "short"

class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"

@dataclass
class Order:
    """Класс для представления ордера"""
    id: int
    timestamp: pd.Timestamp
    order_type: OrderType
    price: float
    quantity: float
    status: OrderStatus = OrderStatus.PENDING
    is_dca: bool = False
    dca_level: int = 0
    is_pyramid: bool = False
    pyramid_level: int = 0

@dataclass
class Position:
    """Класс для представления позиции"""
    symbol: str
    order_type: OrderType
    entry_price: float
    quantity: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    orders: List[Order] = None
    pyramid_stop_price: Optional[float] = None  # SL, подтянутый пирамидингом (переопределяет avg_price*(1±sl%))

    def __post_init__(self):
        if self.orders is None:
            self.orders = []
    
    @property
    def average_price(self) -> float:
        """Вычисляет среднюю цену входа"""
        if not self.orders:
            return self.entry_price
        
        total_cost = sum(order.price * order.quantity for order in self.orders if order.status == OrderStatus.FILLED)
        total_quantity = sum(order.quantity for order in self.orders if order.status == OrderStatus.FILLED)
        
        return total_cost / total_quantity if total_quantity > 0 else self.entry_price
    
    def update_unrealized_pnl(self, current_price: float):
        """Обновляет нереализованную прибыль/убыток"""
        self.current_price = current_price
        avg_price = self.average_price
        
        if self.order_type == OrderType.LONG:
            self.unrealized_pnl = (current_price - avg_price) * self.quantity
        else:  # SHORT
            self.unrealized_pnl = (avg_price - current_price) * self.quantity

class TradingStrategy:
    """
    Базовый класс торговой стратегии с поддержкой DCA и Мартингейл
    """
    
    def __init__(self, config: dict):
        self.config = config
        self.balance = config.get('start_balance', 1000)
        self.initial_balance = self.balance
        self.leverage = config.get('leverage', 1)
        self.positions: List[Position] = []
        self.closed_positions: List[Position] = []
        self.order_id_counter = 1
        self.verbose = False  # Будет установлен из backtester.py
        
        # Параметры для расчета ликвидации
        self.margin_ratio_threshold = 0.8  # Порог для margin call (80%)
        self.liquidation_threshold = 0.5   # Порог для ликвидации (50%)
        self.maintenance_margin = 0.005    # Поддерживающая маржа (0.5%)
        self.initial_margin = 0.1          # Начальная маржа (10%)
        self.funding_rate = 0.0001         # Funding rate (0.01% каждые 8 часов)
        self.commission_rate = 0.0004      # Комиссия биржи (0.04%)
        
        # Параметры стратегии
        self.order_type = OrderType(config.get('order_type', 'long'))
        
        # Take Profit параметры
        self.tp_config = config.get('take_profit', {})
        self.tp_enabled = self.tp_config.get('enabled', True)
        self.take_profit_percent = self.tp_config.get('percent', 5) / 100
        self.tp_trailing = self.tp_config.get('trailing', {})
        
        # Stop Loss параметры
        self.sl_config = config.get('stop_loss', {})
        self.sl_enabled = self.sl_config.get('enabled', True)
        self.stop_loss_percent = self.sl_config.get('percent', 10) / 100
        self.sl_trailing = self.sl_config.get('trailing', {})
        
        # Параметры первого ордера
        self.first_order_config = config.get('first_order', {})
        self.first_order_amount_percent = self.first_order_config.get('amount_percent', 10)
        self.first_order_amount_fixed = self.first_order_config.get('amount_fixed')
        self.first_order_risk_percent = self.first_order_config.get('risk_percent')
        
        # DCA параметры
        self.dca_config = config.get('dca', {})
        self.dca_enabled = self.dca_config.get('enabled', False)
        self.max_dca_orders = self.dca_config.get('max_orders', 5)
        
        # Мартингейл параметры
        self.martingale_config = self.dca_config.get('martingale', {})
        self.martingale_enabled = self.martingale_config.get('enabled', False)
        self.martingale_multiplier = self.martingale_config.get('multiplier', 2.0)
        self.martingale_progression = self.martingale_config.get('progression', 'exponential')
        
        # Динамический шаг цены
        self.step_price_config = self.dca_config.get('step_price', {})
        self.step_price_type = self.step_price_config.get('type', 'fixed_percent')
        self.step_price_value = self.step_price_config.get('value', 1.5) / 100
        self.step_price_dynamic_multiplier = self.step_price_config.get('dynamic_multiplier', 1.0)
        self.step_price_atr_multiplier = self.step_price_config.get('atr_multiplier')

        # Пирамидинг — добавление к позиции ПО тренду (в прибыли), в отличие от DCA (в убытке)
        self.pyramid_config = config.get('pyramid', {})
        self.pyramid_enabled = self.pyramid_config.get('enabled', False)
        self.max_pyramid_orders = self.pyramid_config.get('max_orders', 3)

        self.pyramid_trigger_config = self.pyramid_config.get('trigger', {})
        self.pyramid_trigger_type = self.pyramid_trigger_config.get('type', 'fixed_percent')
        self.pyramid_trigger_value = self.pyramid_trigger_config.get('value', 1.5) / 100
        self.pyramid_trigger_atr_multiplier = self.pyramid_trigger_config.get('atr_multiplier', 1.0)

        self.pyramid_size_progression = self.pyramid_config.get('size_progression', 'decreasing')
        self.pyramid_size_multiplier = self.pyramid_config.get('size_multiplier', 0.5)
        self.pyramid_stop_advance = self.pyramid_config.get('stop_advance', 'to_prev_entry')

        # Параметры входа
        self.entry_config = config.get('entry_conditions', {})
        self.entry_type = self.entry_config.get('type', 'manual')
        
        # Риск-менеджмент
        self.risk_config = config.get('risk_management', {})
        self.max_drawdown_percent = self.risk_config.get('max_drawdown_percent', 20) / 100
        self.max_open_positions = self.risk_config.get('max_open_positions', 1)
        self.daily_loss_limit = self.risk_config.get('daily_loss_limit')
        
        # История сделок
        self.trade_history: List[dict] = []
        
        # Для отслеживания максимумов/минимумов и trailing stops
        self.recent_high = 0.0
        self.recent_low = float('inf')
        self.lookback_period = 20  # Период для поиска локальных экстремумов
        self.trailing_tp_price = None
        self.trailing_sl_price = None
        self.peak_balance = self.balance

        # Для dual timeframe режима (эмуляция Bar Magnifier)
        self.last_processed_strategy_bar = None  # timestamp последней обработанной strategy свечи
        self.calc_on_order_fills = config.get('calc_on_order_fills', True)  # Эмуляция PineScript calc_on_order_fills (по умолчанию True как в Pine)
        self.max_entries_per_bar = config.get('max_entries_per_bar', 1)  # Максимум входов на одной strategy свече
        self.entries_on_current_bar = 0  # Счетчик входов на текущей strategy свече
        
        # Инициализация индикаторов
        self.indicators_enabled = False
        self.indicator_strategy = None
        self.indicator_config = {}
        
        if INDICATORS_AVAILABLE:
            # Проверяем, включены ли индикаторы в конфигурации
            indicators_config = config.get('indicators', {})
            self.indicators_enabled = indicators_config.get('enabled', False)

            if self.indicators_enabled:
                # Проверяем новый формат с независимым выбором индикаторов
                if 'selected_indicators' in indicators_config:
                    # Новый формат - кастомный выбор индикаторов
                    self.indicator_strategy = 'custom'
                    self.indicator_config = indicators_config
                else:
                    # Старый формат - предустановленные стратегии
                    self.indicator_strategy = indicators_config.get('strategy_type', 'trend_momentum')
                    self.indicator_config = indicators_config.get(self.indicator_strategy, {})

                # Инициализируем индикаторы
                self.indicators = TechnicalIndicators()
                self.indicator_strategy_handler = IndicatorStrategy(self.indicators)

                if self.verbose:
                    print(f"Индикаторы включены: {self.indicator_strategy}")
                    print(f"Конфигурация: {self.indicator_config}")
    
    def should_enter_position(self, current_data: pd.Series, historical_data: pd.DataFrame,
                               historical_trend_data: pd.DataFrame = None) -> bool:
        """
        Определяет, следует ли входить в позицию

        Args:
            current_data: текущие данные (строка из DataFrame)
            historical_data: исторические данные для анализа
            historical_trend_data: исторические данные третьего (трендового) таймфрейма,
                напр. 4H для EMA-фильтра — опционально, нужно только стратегиям вида
                mrc_trend_filtered

        Returns:
            True если следует входить в позицию
        """
        if self.has_open_position():
            return False

        # Если индикаторы включены, используем их логику
        if self.indicators_enabled and INDICATORS_AVAILABLE:
            return self._indicator_based_entry_logic(current_data, historical_data, historical_trend_data)

        # Иначе используем базовую логику
        return self._basic_entry_logic(current_data, historical_data)

    def _indicator_based_entry_logic(self, current_data: pd.Series, historical_data: pd.DataFrame,
                                      historical_trend_data: pd.DataFrame = None) -> bool:
        """
        Логика входа на основе технических индикаторов

        Args:
            current_data: текущие данные
            historical_data: исторические данные
            historical_trend_data: исторические данные трендового ТФ (см. should_enter_position)

        Returns:
            True если следует входить в позицию
        """
        try:
            # Новый формат - кастомный выбор индикаторов
            if self.indicator_strategy == 'custom':
                signal_data = self.indicator_strategy_handler.custom_signal(
                    historical_data, self.indicator_config
                )

                if self.order_type == OrderType.LONG:
                    return signal_data['long_signal']
                else:
                    return signal_data['short_signal']

            # Старые предустановленные стратегии
            elif self.indicator_strategy == 'trend_momentum':
                signal_data = self.indicator_strategy_handler.trend_momentum_signal(
                    historical_data, self.indicator_config
                )

                if self.order_type == OrderType.LONG:
                    return signal_data['long_signal']
                else:
                    return signal_data['short_signal']

            elif self.indicator_strategy == 'volatility_bounce':
                signal_data = self.indicator_strategy_handler.volatility_bounce_signal(
                    historical_data, self.indicator_config
                )

                if self.order_type == OrderType.LONG:
                    return signal_data['long_signal']
                else:
                    return signal_data['short_signal']

            elif self.indicator_strategy == 'momentum_trend':
                signal_data = self.indicator_strategy_handler.momentum_trend_signal(
                    historical_data, self.indicator_config
                )

                if self.order_type == OrderType.LONG:
                    return signal_data['long_signal']
                else:
                    return signal_data['short_signal']

            elif self.indicator_strategy == 'mrc_reversion':
                signal_data = self.indicator_strategy_handler.mrc_reversion_signal(
                    historical_data, self.indicator_config
                )

                if self.order_type == OrderType.LONG:
                    return signal_data['long_signal']
                else:
                    return signal_data['short_signal']

            elif self.indicator_strategy == 'mrc_trend_filtered':
                if historical_trend_data is None:
                    if self.verbose:
                        print("mrc_trend_filtered требует historical_trend_data (trend_timeframe в конфиге)")
                    return False

                signal_data = self.indicator_strategy_handler.mrc_trend_filtered_signal(
                    historical_data, self.indicator_config, historical_trend_data
                )

                if self.order_type == OrderType.LONG:
                    return signal_data['long_signal']
                else:
                    return signal_data['short_signal']

            return False

        except Exception as e:
            if self.verbose:
                print(f"Ошибка в индикаторной логике: {e}")
            return False
    
    def _basic_entry_logic(self, current_data: pd.Series, historical_data: pd.DataFrame) -> bool:
        """
        Базовая логика входа в позицию (без индикаторов)
        
        Args:
            current_data: текущие данные (строка из DataFrame)
            historical_data: исторические данные для анализа
            
        Returns:
            True если следует входить в позицию
        """
        current_price = current_data['close']
        
        if self.entry_type == 'immediate':
            # Немедленный вход в позицию (при первой возможности)
            return True
        
        elif self.entry_type == 'manual':
            # Простая логика входа по падению/росту цены
            trigger = self.entry_config.get('trigger', 'price_drop')
            percent = self.entry_config.get('percent', 2) / 100
            
            if len(historical_data) < self.lookback_period:
                return False
            
            # Обновляем недавние максимумы/минимумы
            recent_data = historical_data.tail(self.lookback_period)
            self.recent_high = recent_data['high'].max()
            self.recent_low = recent_data['low'].min()
            
            if trigger == 'price_drop' and self.order_type == OrderType.LONG:
                # Вход в лонг при падении цены от недавнего максимума
                drop_percent = (self.recent_high - current_price) / self.recent_high
                return drop_percent >= percent
                
            elif trigger == 'price_rise' and self.order_type == OrderType.SHORT:
                # Вход в шорт при росте цены от недавнего минимума
                rise_percent = (current_price - self.recent_low) / self.recent_low
                return rise_percent >= percent
        
        return False
    
    def should_add_dca_order(self, current_price: float, position: Position, historical_data: pd.DataFrame = None) -> bool:
        """
        Определяет, следует ли добавить DCA ордер с учетом динамического шага
        
        Args:
            current_price: текущая цена
            position: открытая позиция
            historical_data: исторические данные для расчета ATR
            
        Returns:
            True если следует добавить DCA ордер
        """
        if not self.dca_enabled or not position:
            return False

        # Считаем количество уже размещенных DCA ордеров (пирамид-ордера не считаем — свой лимит)
        dca_orders_count = sum(1 for order in position.orders
                                if order.is_dca and not order.is_pyramid and order.status == OrderStatus.FILLED)

        if dca_orders_count >= self.max_dca_orders:
            return False
        
        # Вычисляем динамический шаг
        step_percent = self._calculate_dynamic_step(dca_orders_count, historical_data)
        
        avg_price = position.average_price
        
        if position.order_type == OrderType.LONG:
            # Для лонга добавляем DCA при падении цены
            price_drop = (avg_price - current_price) / avg_price
            return price_drop >= step_percent
        else:
            # Для шорта добавляем DCA при росте цены
            price_rise = (current_price - avg_price) / avg_price
            return price_rise >= step_percent
    
    def _calculate_dynamic_step(self, dca_level: int, historical_data: pd.DataFrame = None) -> float:
        """
        Вычисляет динамический шаг для DCA ордера
        
        Args:
            dca_level: уровень DCA ордера
            historical_data: исторические данные для расчета ATR
            
        Returns:
            Процент шага для DCA
        """
        base_step = self.step_price_value
        
        if self.step_price_type == 'fixed_percent':
            return base_step
        
        elif self.step_price_type == 'dynamic_percent':
            # Увеличиваем шаг с каждым уровнем
            multiplier = self.step_price_dynamic_multiplier ** dca_level
            return base_step * multiplier
        
        elif self.step_price_type == 'atr_based' and historical_data is not None:
            # Используем ATR для расчета шага
            if self.indicators_enabled and INDICATORS_AVAILABLE:
                # Используем библиотеку ta для ATR
                atr = self.indicators.calculate_atr(
                    historical_data['high'], 
                    historical_data['low'], 
                    historical_data['close'], 
                    14,  # период ATR
                    "atr_dca"
                )
                current_atr = atr.iloc[-1]
                current_price = historical_data['close'].iloc[-1]
                
                if current_atr > 0 and current_price > 0:
                    atr_multiplier = self.step_price_atr_multiplier or 1.0
                    # ATR как процент от цены
                    atr_percent = (current_atr / current_price) * 100
                    
                    # Применяем прогрессию если включен мартингейл
                    if self.martingale_enabled:
                        multiplier = self.martingale_multiplier ** dca_level
                        return atr_percent * multiplier
                    else:
                        return atr_percent * atr_multiplier
                else:
                    return base_step
            else:
                # Fallback к простому ATR расчету
                atr = self._calculate_atr(historical_data)
                if atr > 0:
                    atr_multiplier = self.step_price_atr_multiplier or 1.0
                    return (atr / historical_data['close'].iloc[-1]) * atr_multiplier
                else:
                    return base_step

        return base_step

    def should_add_pyramid_order(self, current_price: float, position: Position, historical_data: pd.DataFrame = None) -> bool:
        """
        Определяет, следует ли добавить пирамид-ордер (докупка ПО тренду, в прибыли)

        В отличие от DCA (усреднение в убытке), пирамидинг добавляет объём
        когда цена уже прошла в нужную сторону — триггер считается от цены
        ПОСЛЕДНЕГО исполненного ордера, а не от средней (иначе шаг "съезжает"
        по мере роста position.average_price).

        Args:
            current_price: текущая цена
            position: открытая позиция
            historical_data: исторические данные для расчета ATR-шага

        Returns:
            True если следует добавить пирамид-ордер
        """
        if not self.pyramid_enabled or not position:
            return False

        pyramid_orders_count = sum(1 for order in position.orders if order.is_pyramid and order.status == OrderStatus.FILLED)

        if pyramid_orders_count >= self.max_pyramid_orders:
            return False

        filled_orders = [o for o in position.orders if o.status == OrderStatus.FILLED]
        if not filled_orders:
            return False
        last_entry_price = filled_orders[-1].price

        step_percent = self._calculate_pyramid_step(pyramid_orders_count, historical_data)

        if position.order_type == OrderType.LONG:
            # Для лонга добавляем пирамид-ордер при росте цены от последнего входа
            price_rise = (current_price - last_entry_price) / last_entry_price
            return price_rise >= step_percent
        else:
            # Для шорта — при падении цены от последнего входа
            price_drop = (last_entry_price - current_price) / last_entry_price
            return price_drop >= step_percent

    def _calculate_pyramid_step(self, pyramid_level: int, historical_data: pd.DataFrame = None) -> float:
        """
        Вычисляет шаг (в %) для следующего пирамид-ордера

        Args:
            pyramid_level: сколько пирамид-ордеров уже исполнено
            historical_data: исторические данные для ATR-шага

        Returns:
            Процент шага для пирамидинга
        """
        base_step = self.pyramid_trigger_value

        if self.pyramid_trigger_type == 'atr_based' and historical_data is not None:
            if self.indicators_enabled and INDICATORS_AVAILABLE:
                atr = self.indicators.calculate_atr(
                    historical_data['high'],
                    historical_data['low'],
                    historical_data['close'],
                    14,
                    None  # без кэша — идентично DCA atr_based
                )
                current_atr = atr.iloc[-1]
                current_price = historical_data['close'].iloc[-1]

                if current_atr > 0 and current_price > 0:
                    atr_percent = (current_atr / current_price) * 100
                    return atr_percent * self.pyramid_trigger_atr_multiplier
            return base_step

        return base_step

    def _calculate_pyramid_size_multiplier(self, pyramid_level: int) -> float:
        """
        Вычисляет мультипликатор размера для пирамид-ордера (обычно убывающий —
        в отличие от мартингейла, где объём растёт по мере убытка).

        Args:
            pyramid_level: 0-индексированный уровень пирамид-ордера (0 = первое добавление)

        Returns:
            Мультипликатор от базового order size
        """
        if self.pyramid_size_progression == 'decreasing':
            return self.pyramid_size_multiplier ** (pyramid_level + 1)
        else:  # 'fixed'
            return 1.0

    def calculate_margin_ratio(self, position: Position, current_price: float) -> float:
        """
        Рассчитывает коэффициент маржи
        
        Args:
            position: открытая позиция
            current_price: текущая цена
            
        Returns:
            Коэффициент маржи (0-1)
        """
        if not position:
            return 1.0
        
        # Рассчитываем нереализованную прибыль/убыток
        position.update_unrealized_pnl(current_price)
        
        # Общая стоимость позиции
        position_value = position.quantity * current_price
        
        # Доступная маржа = баланс + нереализованная прибыль
        available_margin = self.balance + position.unrealized_pnl
        
        # Требуемая маржа = стоимость позиции / плечо
        required_margin = position_value / self.leverage
        
        if required_margin <= 0:
            return 1.0
        
        return available_margin / required_margin
    
    def calculate_liquidation_price(self, position: Position) -> float:
        """
        Рассчитывает цену ликвидации для позиции
        
        Args:
            position: открытая позиция
            
        Returns:
            Цена ликвидации
        """
        if not position:
            return 0.0
        
        avg_price = position.average_price
        
        if position.order_type == OrderType.LONG:
            # Для лонга: цена ликвидации = средняя цена - (баланс * плечо / количество)
            liquidation_price = avg_price - (self.balance * self.leverage / position.quantity)
        else:
            # Для шорта: цена ликвидации = средняя цена + (баланс * плечо / количество)
            liquidation_price = avg_price + (self.balance * self.leverage / position.quantity)
        
        return max(liquidation_price, 0.0)
    
    def check_margin_call(self, position: Position, current_price: float) -> Tuple[bool, str]:
        """
        Проверяет margin call и ликвидацию
        
        Args:
            position: открытая позиция
            current_price: текущая цена
            
        Returns:
            Tuple (произошла_ли_ликвидация, причина)
        """
        if not position:
            return False, ""
        
        margin_ratio = self.calculate_margin_ratio(position, current_price)
        liquidation_price = self.calculate_liquidation_price(position)
        
        # Проверяем ликвидацию
        if position.order_type == OrderType.LONG and current_price <= liquidation_price:
            return True, "liquidation_price_reached"
        elif position.order_type == OrderType.SHORT and current_price >= liquidation_price:
            return True, "liquidation_price_reached"
        
        # Проверяем margin call
        if margin_ratio <= self.liquidation_threshold:
            return True, "margin_call_liquidation"
        elif margin_ratio <= self.margin_ratio_threshold:
            return True, "margin_call_warning"
        
        return False, ""
    
    def _calculate_atr(self, data: pd.DataFrame, period: int = 14) -> float:
        """
        Вычисляет Average True Range (ATR)
        
        Args:
            data: исторические данные OHLC
            period: период для расчета ATR
            
        Returns:
            Значение ATR
        """
        if len(data) < period + 1:
            return 0
        
        high = data['high']
        low = data['low']
        close = data['close'].shift(1)
        
        tr1 = high - low
        tr2 = abs(high - close)
        tr3 = abs(low - close)
        
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.rolling(window=period).mean().iloc[-1]
        
        return atr if not pd.isna(atr) else 0
    
    def calculate_order_quantity(self, price: float, is_dca: bool = False, dca_level: int = 0,
                                  is_pyramid: bool = False, pyramid_level: int = 0) -> float:
        """
        Вычисляет размер ордера с учетом плеча и различных методов расчета
        Мартингейл применяется к количеству монет, а не к долларовой сумме

        ВАЖНО: base_amount - это размер ПОЗИЦИИ (не маржи!)
        Например: 10 USD = позиция на 10 USD, при плече 10x маржа будет 1 USD

        Args:
            price: цена исполнения
            is_dca: является ли ордер DCA
            dca_level: уровень DCA ордера
            is_pyramid: является ли ордер пирамид-добавлением
            pyramid_level: 0-индексированный уровень пирамид-ордера

        Returns:
            Размер ордера (в монетах)
        """
        # Проверяем максимальную просадку
        current_drawdown = (self.peak_balance - self.balance) / self.peak_balance
        if current_drawdown >= self.max_drawdown_percent:
            return 0  # Не открываем новые позиции при превышении просадки

        # Рассчитываем базовую сумму = РАЗМЕР ПОЗИЦИИ (не маржи!)
        if self.first_order_amount_fixed:
            # Фиксированная сумма = размер позиции
            base_position_size = self.first_order_amount_fixed
        elif self.first_order_risk_percent:
            # Расчет на основе риска (процент от баланса при стоп-лоссе)
            risk_amount = self.balance * (self.first_order_risk_percent / 100)
            if self.sl_enabled and self.stop_loss_percent > 0:
                base_position_size = risk_amount / self.stop_loss_percent
            else:
                base_position_size = risk_amount
        else:
            # Процент от баланса
            if self.first_order_amount_percent is not None:
                # Процент от баланса с учётом плеча
                margin = self.balance * (self.first_order_amount_percent / 100)
                base_position_size = margin * self.leverage
            else:
                # Если процент не указан, используем фиксированную сумму или 10% по умолчанию
                if self.first_order_amount_fixed:
                    base_position_size = self.first_order_amount_fixed
                else:
                    margin = self.balance * 0.1
                    base_position_size = margin * self.leverage

        # Переводим размер позиции в количество монет ПО ТЕКУЩЕЙ ЦЕНЕ
        base_quantity = base_position_size / price

        # Для DCA ордеров применяем мартингейл к КОЛИЧЕСТВУ монет
        # (is_pyramid проверяем первым явно — пирамид-ордера тоже помечены
        # is_dca=True, но должны идти по своей ветке даже если пользователь
        # одновременно включил dca.martingale и pyramid в одном конфиге)
        if is_pyramid:
            # Пирамидинг: убывающий (по умолчанию) размер ордера относительно базового
            multiplier = self._calculate_pyramid_size_multiplier(pyramid_level)
            order_quantity = base_quantity * multiplier
        elif is_dca and self.martingale_enabled:
            if self.martingale_progression == 'exponential':
                multiplier = self.martingale_multiplier ** dca_level
            elif self.martingale_progression == 'linear':
                multiplier = 1 + (self.martingale_multiplier - 1) * dca_level
            else:  # fibonacci
                multiplier = self._fibonacci_multiplier(dca_level)

            order_quantity = base_quantity * multiplier
        else:
            order_quantity = base_quantity

        # Проверяем лимиты баланса (проверяем МАРЖУ, а не полную стоимость)
        order_value = order_quantity * price
        required_margin = order_value / self.leverage

        # Оставляем 10% резерва баланса
        if required_margin > self.balance * 0.9:
            max_margin = self.balance * 0.9
            max_position_value = max_margin * self.leverage
            order_quantity = max_position_value / price

        return order_quantity
    
    def _fibonacci_multiplier(self, level: int) -> float:
        """Вычисляет мультипликатор по последовательности Фибоначчи"""
        if level <= 0:
            return 1
        elif level == 1:
            return 1
        else:
            a, b = 1, 1
            for _ in range(level - 1):
                a, b = b, a + b
            return b
    
    def create_order(self, timestamp: pd.Timestamp, price: float, is_dca: bool = False, dca_level: int = 0,
                      is_pyramid: bool = False, pyramid_level: int = 0) -> Order:
        """Создает новый ордер"""
        quantity = self.calculate_order_quantity(price, is_dca, dca_level, is_pyramid, pyramid_level)

        order = Order(
            id=self.order_id_counter,
            timestamp=timestamp,
            order_type=self.order_type,
            price=price,
            quantity=quantity,
            is_dca=is_dca,
            dca_level=dca_level,
            is_pyramid=is_pyramid,
            pyramid_level=pyramid_level
        )

        self.order_id_counter += 1
        return order
    
    def execute_order(self, order: Order) -> bool:
        """
        Исполняет ордер с учётом плеча

        Args:
            order: ордер для исполнения

        Returns:
            True если ордер успешно исполнен
        """
        # Полная стоимость позиции
        order_value = order.price * order.quantity

        # Требуемая маржа = стоимость позиции / плечо
        margin_required = order_value / self.leverage

        # Комиссия рассчитывается от полной стоимости позиции
        commission = order_value * self.commission_rate

        # Итоговая сумма к списанию = маржа + комиссия
        total_cost = margin_required + commission

        # Проверяем, достаточно ли средств
        if total_cost > self.balance:
            if self.verbose:
                print(f"[ORDER REJECTED] Недостаточно средств. Требуется: ${total_cost:.2f}, доступно: ${self.balance:.2f}")
            return False

        # Списываем средства (только маржу + комиссию)
        self.balance -= total_cost
        order.status = OrderStatus.FILLED

        if self.verbose:
            print(f"[ORDER EXECUTED] Маржа: ${margin_required:.2f} | Комиссия: ${commission:.4f} | Списано: ${total_cost:.2f}")
        
        # Создаем или обновляем позицию
        if not self.has_open_position():
            # Создаем новую позицию
            position = Position(
                symbol=self.config.get('symbol', 'UNKNOWN'),
                order_type=order.order_type,
                entry_price=order.price,
                quantity=order.quantity,
                orders=[order]
            )
            self.positions.append(position)
        else:
            # Добавляем к существующей позиции
            position = self.get_open_position()

            # Подтягиваем SL к цене ПРЕДЫДУЩЕГО входа (до добавления этого ордера)
            # — классический пирамидинг: стоп двигается за ценой, фиксируя часть прибыли
            if order.is_pyramid and self.pyramid_stop_advance == 'to_prev_entry':
                filled_before = [o for o in position.orders if o.status == OrderStatus.FILLED]
                if filled_before:
                    position.pyramid_stop_price = filled_before[-1].price

            position.orders.append(order)
            position.quantity += order.quantity

        return True
    
    def check_intrabar_exit(self, current_data: pd.Series, position: Position) -> Tuple[bool, str, float]:
        """
        Проверяет достижение TP/SL внутри свечи используя high/low

        ВАЖНО: Учитывает направление свечи для определения последовательности событий.
        Если и TP и SL достигнуты на одной свече, выбирается тот что произошел раньше.

        Логика (как в PineScript Bar Magnifier):
        - Растущая свеча (close >= open): цена сначала шла вверх → для LONG сначала TP
        - Падающая свеча (close < open): цена сначала шла вниз → для LONG сначала SL

        Args:
            current_data: данные текущей свечи (должны содержать open, high, low, close)
            position: открытая позиция

        Returns:
            Tuple (сработал_exit, причина, цена_выхода)
        """
        if not position:
            return False, "", 0.0

        high = current_data.get('high', current_data['close'])
        low = current_data.get('low', current_data['close'])
        close = current_data['close']
        open_price = current_data.get('open', current_data['close'])
        avg_price = position.average_price

        # Определяем направление свечи
        is_bullish_candle = close >= open_price

        if position.order_type == OrderType.LONG:
            # Рассчитываем уровни TP и SL
            tp_price = None
            sl_price = None

            if self.tp_enabled:
                tp_price = avg_price * (1 + self.take_profit_percent)
            if self.sl_enabled:
                sl_price = position.pyramid_stop_price if position.pyramid_stop_price is not None \
                    else avg_price * (1 - self.stop_loss_percent)

            # Проверяем достижение уровней
            tp_hit = tp_price is not None and high >= tp_price
            sl_hit = sl_price is not None and low <= sl_price

            # Если оба уровня достигнуты - определяем что произошло раньше
            if tp_hit and sl_hit:
                # Растущая свеча: цена сначала росла (TP) потом могла упасть (SL)
                # Падающая свеча: цена сначала падала (SL) потом могла вырасти (TP)
                if is_bullish_candle:
                    return True, "take_profit", tp_price
                else:
                    return True, "stop_loss", sl_price
            elif tp_hit:
                return True, "take_profit", tp_price
            elif sl_hit:
                return True, "stop_loss", sl_price

        else:  # SHORT
            # Для шорта уровни инвертированы
            tp_price = None
            sl_price = None

            if self.tp_enabled:
                tp_price = avg_price * (1 - self.take_profit_percent)
            if self.sl_enabled:
                sl_price = position.pyramid_stop_price if position.pyramid_stop_price is not None \
                    else avg_price * (1 + self.stop_loss_percent)

            # Проверяем достижение уровней
            tp_hit = tp_price is not None and low <= tp_price
            sl_hit = sl_price is not None and high >= sl_price

            # Если оба уровня достигнуты - определяем что произошло раньше
            if tp_hit and sl_hit:
                # Растущая свеча: цена росла (для SHORT это плохо) → сначала SL
                # Падающая свеча: цена падала (для SHORT это хорошо) → сначала TP
                if is_bullish_candle:
                    return True, "stop_loss", sl_price
                else:
                    return True, "take_profit", tp_price
            elif tp_hit:
                return True, "take_profit", tp_price
            elif sl_hit:
                return True, "stop_loss", sl_price

        return False, "", 0.0

    def should_close_position(self, current_price: float, position: Position) -> Tuple[bool, str]:
        """
        Определяет, следует ли закрыть позицию с учетом trailing stops
        
        Args:
            current_price: текущая цена
            position: открытая позиция
            
        Returns:
            Tuple (следует_ли_закрыть, причина)
        """
        if not position:
            return False, ""
        
        avg_price = position.average_price
        
        # Обновляем пиковый баланс для риск-менеджмента
        if self.balance > self.peak_balance:
            self.peak_balance = self.balance
        
        # Проверяем максимальную просадку на основе нереализованного PnL
        position.update_unrealized_pnl(current_price)
        if position.unrealized_pnl < 0:  # Только если в убытке
            # Рассчитываем просадку от стоимости позиции, а не от баланса
            position_cost = sum(order.price * order.quantity for order in position.orders 
                              if order.status == OrderStatus.FILLED)
            unrealized_loss_percent = abs(position.unrealized_pnl) / position_cost
            
            if self.verbose:
                print(f"🔍 ПРОВЕРКА ПРОСАДКИ: Убыток ${abs(position.unrealized_pnl):.2f} ({unrealized_loss_percent*100:.2f}%) | Лимит: {self.max_drawdown_percent*100:.1f}%")
            
            if unrealized_loss_percent >= self.max_drawdown_percent:
                if self.verbose:
                    print(f"🛑 ПРОСАДКА ПРЕВЫШЕНА: {unrealized_loss_percent*100:.2f}% >= {self.max_drawdown_percent*100:.1f}%")
                return True, "max_drawdown_reached"
        
        if position.order_type == OrderType.LONG:
            # Для лонг позиции
            profit_percent = (current_price - avg_price) / avg_price
            loss_percent = (avg_price - current_price) / avg_price
            
            # Проверяем trailing take profit
            if self.tp_enabled and self.tp_trailing.get('enabled', False):
                tp_activation = self.tp_trailing.get('activation_percent', 3) / 100
                tp_trail = self.tp_trailing.get('trail_percent', 1) / 100
                
                if profit_percent >= tp_activation:
                    if self.trailing_tp_price is None:
                        self.trailing_tp_price = current_price * (1 - tp_trail)
                    else:
                        new_trailing_price = current_price * (1 - tp_trail)
                        if new_trailing_price > self.trailing_tp_price:
                            self.trailing_tp_price = new_trailing_price
                    
                    if current_price <= self.trailing_tp_price:
                        return True, "trailing_take_profit"
            
            # Проверяем trailing stop loss
            if self.sl_enabled and self.sl_trailing.get('enabled', False):
                sl_activation = self.sl_trailing.get('activation_percent', 2) / 100
                sl_trail = self.sl_trailing.get('trail_percent', 0.5) / 100
                
                if profit_percent >= sl_activation:
                    if self.trailing_sl_price is None:
                        self.trailing_sl_price = current_price * (1 - sl_trail)
                    else:
                        new_trailing_price = current_price * (1 - sl_trail)
                        if new_trailing_price > self.trailing_sl_price:
                            self.trailing_sl_price = new_trailing_price
                    
                    if current_price <= self.trailing_sl_price:
                        return True, "trailing_stop_loss"
            
            # Обычные take profit и stop loss
            if self.verbose:
                print(f"🔍 TP/SL ПРОВЕРКА (LONG): Прибыль {profit_percent*100:.2f}% | Убыток {loss_percent*100:.2f}% | TP: {self.take_profit_percent*100:.1f}% | SL: {self.stop_loss_percent*100:.1f}%")
            
            if self.tp_enabled and profit_percent >= self.take_profit_percent:
                if self.verbose:
                    print(f"✅ TAKE PROFIT (LONG): {profit_percent*100:.2f}% >= {self.take_profit_percent*100:.1f}%")
                return True, "take_profit"
            elif self.sl_enabled and position.pyramid_stop_price is not None:
                if current_price <= position.pyramid_stop_price:
                    if self.verbose:
                        print(f"🛑 STOP LOSS (LONG, pyramid): цена ${current_price:.4f} <= стоп ${position.pyramid_stop_price:.4f}")
                    return True, "stop_loss"
            elif self.sl_enabled and loss_percent >= self.stop_loss_percent:
                if self.verbose:
                    print(f"🛑 STOP LOSS (LONG): {loss_percent*100:.2f}% >= {self.stop_loss_percent*100:.1f}%")
                return True, "stop_loss"

        else:  # SHORT
            # Для шорт позиции
            profit_percent = (avg_price - current_price) / avg_price
            loss_percent = (current_price - avg_price) / avg_price
            
            # Проверяем trailing take profit для шорта
            if self.tp_enabled and self.tp_trailing.get('enabled', False):
                tp_activation = self.tp_trailing.get('activation_percent', 3) / 100
                tp_trail = self.tp_trailing.get('trail_percent', 1) / 100
                
                if profit_percent >= tp_activation:
                    if self.trailing_tp_price is None:
                        self.trailing_tp_price = current_price * (1 + tp_trail)
                    else:
                        new_trailing_price = current_price * (1 + tp_trail)
                        if new_trailing_price < self.trailing_tp_price:
                            self.trailing_tp_price = new_trailing_price
                    
                    if current_price >= self.trailing_tp_price:
                        return True, "trailing_take_profit"
            
            # Проверяем trailing stop loss для шорта
            if self.sl_enabled and self.sl_trailing.get('enabled', False):
                sl_activation = self.sl_trailing.get('activation_percent', 2) / 100
                sl_trail = self.sl_trailing.get('trail_percent', 0.5) / 100
                
                if profit_percent >= sl_activation:
                    if self.trailing_sl_price is None:
                        self.trailing_sl_price = current_price * (1 + sl_trail)
                    else:
                        new_trailing_price = current_price * (1 + sl_trail)
                        if new_trailing_price < self.trailing_sl_price:
                            self.trailing_sl_price = new_trailing_price
                    
                    if current_price >= self.trailing_sl_price:
                        return True, "trailing_stop_loss"
            
            # Обычные take profit и stop loss
            if self.verbose:
                print(f"🔍 TP/SL ПРОВЕРКА (SHORT): Прибыль {profit_percent*100:.2f}% | Убыток {loss_percent*100:.2f}% | TP: {self.take_profit_percent*100:.1f}% | SL: {self.stop_loss_percent*100:.1f}%")
            
            if self.tp_enabled and profit_percent >= self.take_profit_percent:
                if self.verbose:
                    print(f"✅ TAKE PROFIT (SHORT): {profit_percent*100:.2f}% >= {self.take_profit_percent*100:.1f}%")
                return True, "take_profit"
            elif self.sl_enabled and position.pyramid_stop_price is not None:
                if current_price >= position.pyramid_stop_price:
                    if self.verbose:
                        print(f"🛑 STOP LOSS (SHORT, pyramid): цена ${current_price:.4f} >= стоп ${position.pyramid_stop_price:.4f}")
                    return True, "stop_loss"
            elif self.sl_enabled and loss_percent >= self.stop_loss_percent:
                if self.verbose:
                    print(f"🛑 STOP LOSS (SHORT): {loss_percent*100:.2f}% >= {self.stop_loss_percent*100:.1f}%")
                return True, "stop_loss"

        return False, ""
    
    def close_position(self, current_price: float, timestamp: pd.Timestamp, reason: str) -> dict:
        """
        Закрывает открытую позицию
        
        Args:
            current_price: цена закрытия
            timestamp: время закрытия
            reason: причина закрытия
            
        Returns:
            Информация о закрытой сделке
        """
        position = self.get_open_position()
        if not position:
            return {}
        
        # Вычисляем прибыль/убыток
        avg_price = position.average_price

        if position.order_type == OrderType.LONG:
            pnl = (current_price - avg_price) * position.quantity
        else:  # SHORT
            pnl = (avg_price - current_price) * position.quantity

        # Вычисляем комиссию за закрытие (от полной стоимости)
        close_value = current_price * position.quantity
        close_commission = close_value * self.commission_rate

        # Вычисляем общую маржу, которая была заблокирована
        # Это сумма всех маржей от всех ордеров в позиции
        total_margin_used = sum(
            (order.price * order.quantity / self.leverage)
            for order in position.orders
        )

        # Возвращаем маржу + PnL - комиссия за закрытие
        self.balance += total_margin_used + pnl - close_commission

        # Учитываем комиссию за закрытие в PnL
        pnl -= close_commission

        # Учитываем комиссии за открытие (уже списаны при execute_order)
        total_open_commission = sum(
            (order.price * order.quantity * self.commission_rate)
            for order in position.orders
        )
        pnl -= total_open_commission
        
        # Записываем сделку в историю
        trade_info = {
            'symbol': position.symbol,
            'type': position.order_type.value,  # 'long' or 'short'
            'order_type': position.order_type.value,  # Для обратной совместимости
            'entry_price': position.entry_price,  # Цена первого ордера
            'average_price': avg_price,           # Средняя цена всех ордеров
            'exit_price': current_price,
            'volume': position.quantity,  # Добавляем volume для совместимости с шаблоном
            'quantity': position.quantity,
            'pnl': pnl,
            'pnl_percent': (pnl / (avg_price * position.quantity)) * 100,
            'entry_time': position.orders[0].timestamp,
            'exit_time': timestamp,
            'reason': reason,
            'dca_orders_count': sum(1 for order in position.orders if order.is_dca and not order.is_pyramid),
            'pyramid_orders_count': sum(1 for order in position.orders if order.is_pyramid),
            'total_orders': len(position.orders)
        }
        
        self.trade_history.append(trade_info)
        
        # Сбрасываем trailing stops
        self.trailing_tp_price = None
        self.trailing_sl_price = None
        
        # Перемещаем позицию в закрытые
        self.closed_positions.append(position)
        self.positions.remove(position)
        
        return trade_info
    
    def has_open_position(self) -> bool:
        """Проверяет, есть ли открытые позиции"""
        return len(self.positions) > 0
    
    def get_open_position(self) -> Optional[Position]:
        """Возвращает открытую позицию (если есть)"""
        return self.positions[0] if self.positions else None
    
    def process_tick(self, current_data: pd.Series, historical_data: pd.DataFrame,
                      historical_trend_data: pd.DataFrame = None) -> List[dict]:
        """
        Обрабатывает один тик данных (single timeframe режим)

        Args:
            current_data: текущие данные
            historical_data: исторические данные
            historical_trend_data: исторические данные опционального третьего
                (трендового) таймфрейма, напр. 4H для EMA-фильтра — только для
                индикаторных стратегий вида mrc_trend_filtered

        Returns:
            Список действий, выполненных на этом тике
        """
        actions = []
        current_price = current_data['close']
        timestamp = current_data['timestamp']

        # Обновляем нереализованную прибыль для открытых позиций
        if self.has_open_position():
            position = self.get_open_position()
            position.update_unrealized_pnl(current_price)

        # Проверяем условия входа
        if self.should_enter_position(current_data, historical_data, historical_trend_data):
            order = self.create_order(timestamp, current_price)
            if self.execute_order(order):
                actions.append({
                    'action': 'open_position',
                    'order_id': order.id,
                    'price': current_price,
                    'quantity': order.quantity,
                    'timestamp': timestamp
                })

        # Проверяем DCA условия
        elif self.has_open_position():
            position = self.get_open_position()

            if self.should_add_dca_order(current_price, position, historical_data):
                dca_level = sum(1 for order in position.orders if order.is_dca and not order.is_pyramid) + 1
                dca_order = self.create_order(timestamp, current_price, is_dca=True, dca_level=dca_level)

                if self.execute_order(dca_order):
                    actions.append({
                        'action': 'dca_order',
                        'order_id': dca_order.id,
                        'price': current_price,
                        'quantity': dca_order.quantity,
                        'dca_level': dca_level,
                        'timestamp': timestamp
                    })

            elif self.should_add_pyramid_order(current_price, position, historical_data):
                pyramid_level = sum(1 for order in position.orders if order.is_pyramid)
                pyramid_order = self.create_order(timestamp, current_price, is_dca=True,
                                                   is_pyramid=True, pyramid_level=pyramid_level)

                if self.execute_order(pyramid_order):
                    actions.append({
                        'action': 'pyramid_order',
                        'order_id': pyramid_order.id,
                        'price': current_price,
                        'quantity': pyramid_order.quantity,
                        'pyramid_level': pyramid_level,
                        'timestamp': timestamp
                    })

        # СНАЧАЛА проверяем внутрисвечный выход через high/low (приоритет!)
        if self.has_open_position():
            position = self.get_open_position()
            intrabar_exit, reason, exit_price = self.check_intrabar_exit(current_data, position)

            if intrabar_exit:
                trade_info = self.close_position(exit_price, timestamp, reason)
                actions.append({
                    'action': 'close_position',
                    'trade_info': trade_info,
                    'timestamp': timestamp,
                    'exit_type': 'intrabar'  # Пометка что выход внутри свечи
                })
                return actions

        # ПОТОМ проверяем обычные условия выхода (trailing stops, просадка и т.д.)
        if self.has_open_position():
            position = self.get_open_position()
            should_close, reason = self.should_close_position(current_price, position)

            if should_close:
                trade_info = self.close_position(current_price, timestamp, reason)
                actions.append({
                    'action': 'close_position',
                    'trade_info': trade_info,
                    'timestamp': timestamp,
                    'exit_type': 'close_price'  # Выход по цене закрытия
                })
                return actions  # Прерываем выполнение при закрытии позиции

        # Проверяем margin call и ликвидацию (только если позиция еще открыта)
        if self.has_open_position():
            position = self.get_open_position()
            margin_call, margin_reason = self.check_margin_call(position, current_price)

            if margin_call:
                trade_info = self.close_position(current_price, timestamp, margin_reason)
                actions.append({
                    'action': 'margin_call',
                    'trade_info': trade_info,
                    'timestamp': timestamp,
                    'reason': margin_reason
                })
                return actions  # Прерываем выполнение при ликвидации

        return actions

    def process_tick_dual(self,
                         current_exec_data: pd.Series,
                         historical_exec_data: pd.DataFrame,
                         current_strategy_data: pd.Series,
                         historical_strategy_data: pd.DataFrame,
                         historical_trend_data: pd.DataFrame = None) -> List[dict]:
        """
        Обрабатывает один тик в dual timeframe режиме (эмуляция TradingView Bar Magnifier)

        Логика как в PineScript:
        - Сигналы входа проверяются ТОЛЬКО при новой strategy свече
        - TP/SL проверяются на КАЖДОЙ execution свече
        - calc_on_order_fills: после закрытия можно проверить новый сигнал

        Args:
            current_exec_data: текущие execution данные (1m)
            historical_exec_data: исторические execution данные (1m)
            current_strategy_data: текущие strategy данные (15m)
            historical_strategy_data: исторические strategy данные (15m)
            historical_trend_data: исторические данные опционального третьего
                (трендового) таймфрейма, напр. 4H для EMA-фильтра — только для
                индикаторных стратегий вида mrc_trend_filtered

        Returns:
            Список действий, выполненных на этом тике
        """
        actions = []
        current_price = current_exec_data['close']
        timestamp = current_exec_data['timestamp']
        strategy_bar_timestamp = current_strategy_data['timestamp']

        # Обновляем нереализованную прибыль для открытых позиций
        if self.has_open_position():
            position = self.get_open_position()
            position.update_unrealized_pnl(current_price)

        # ✅ ПРАВИЛЬНО: Определяем новую strategy свечу (как в Bar Magnifier)
        is_new_strategy_bar = (
            self.last_processed_strategy_bar is None or
            strategy_bar_timestamp > self.last_processed_strategy_bar
        )

        # ✅ Проверяем сигналы входа ТОЛЬКО при новой strategy свече (как в PineScript)
        if is_new_strategy_bar:
            self.last_processed_strategy_bar = strategy_bar_timestamp
            self.entries_on_current_bar = 0  # Сбрасываем счетчик входов на новой свече

            # Проверяем условия входа ТОЛЬКО на новой strategy свече
            if not self.has_open_position():
                if self.should_enter_position(current_strategy_data, historical_strategy_data, historical_trend_data):
                    # Входим сразу по текущей execution цене
                    order = self.create_order(timestamp, current_price)
                    if self.execute_order(order):
                        self.entries_on_current_bar += 1  # Увеличиваем счетчик
                        actions.append({
                            'action': 'open_position',
                            'order_id': order.id,
                            'price': current_price,
                            'quantity': order.quantity,
                            'timestamp': timestamp
                        })

        # ✅ DCA проверяем на каждой execution свече (цена может упасть между strategy свечами)
        if self.has_open_position():
            position = self.get_open_position()

            if self.should_add_dca_order(current_price, position, historical_strategy_data):
                dca_level = sum(1 for order in position.orders if order.is_dca and not order.is_pyramid) + 1
                dca_order = self.create_order(timestamp, current_price, is_dca=True, dca_level=dca_level)

                if self.execute_order(dca_order):
                    actions.append({
                        'action': 'dca_order',
                        'order_id': dca_order.id,
                        'price': current_price,
                        'quantity': dca_order.quantity,
                        'dca_level': dca_level,
                        'timestamp': timestamp
                    })

            elif self.should_add_pyramid_order(current_price, position, historical_strategy_data):
                pyramid_level = sum(1 for order in position.orders if order.is_pyramid)
                pyramid_order = self.create_order(timestamp, current_price, is_dca=True,
                                                   is_pyramid=True, pyramid_level=pyramid_level)

                if self.execute_order(pyramid_order):
                    actions.append({
                        'action': 'pyramid_order',
                        'order_id': pyramid_order.id,
                        'price': current_price,
                        'quantity': pyramid_order.quantity,
                        'pyramid_level': pyramid_level,
                        'timestamp': timestamp
                    })

        # ✅ ПРИОРИТЕТ 1: Проверяем intrabar exit через high/low (точное определение TP/SL)
        # Это критично для dual timeframe режима, так как execution свечи могут быть мелкими
        if self.has_open_position():
            position = self.get_open_position()
            intrabar_exit, reason, exit_price = self.check_intrabar_exit(current_exec_data, position)

            if intrabar_exit:
                trade_info = self.close_position(exit_price, timestamp, reason)
                actions.append({
                    'action': 'close_position',
                    'trade_info': trade_info,
                    'timestamp': timestamp,
                    'exit_type': 'intrabar'  # Выход внутри свечи по high/low
                })

                # ✅ Эмуляция calc_on_order_fills (как в PineScript)
                # После закрытия позиции можем сразу проверить новый сигнал на текущей strategy свече
                if self.calc_on_order_fills and not is_new_strategy_bar:
                    # Проверяем что не превышен лимит входов на одной свече
                    if self.entries_on_current_bar < self.max_entries_per_bar:
                        # Проверяем можем ли войти снова
                        if self.should_enter_position(current_strategy_data, historical_strategy_data, historical_trend_data):
                            order = self.create_order(timestamp, current_price)
                            if self.execute_order(order):
                                self.entries_on_current_bar += 1  # Увеличиваем счетчик
                                actions.append({
                                    'action': 'open_position',
                                    'order_id': order.id,
                                    'price': current_price,
                                    'quantity': order.quantity,
                                    'timestamp': timestamp
                                })

                return actions  # Прерываем выполнение при закрытии позиции

        # ✅ ПРИОРИТЕТ 2: TP/SL проверяем по close price (trailing stops, просадка и т.д.)
        if self.has_open_position():
            position = self.get_open_position()
            should_close, reason = self.should_close_position(current_price, position)

            if should_close:
                trade_info = self.close_position(current_price, timestamp, reason)
                actions.append({
                    'action': 'close_position',
                    'trade_info': trade_info,
                    'timestamp': timestamp,
                    'exit_type': 'close_price'  # Выход по цене закрытия
                })

                # ✅ Эмуляция calc_on_order_fills (как в PineScript)
                # После закрытия позиции можем сразу проверить новый сигнал на текущей strategy свече
                if self.calc_on_order_fills and not is_new_strategy_bar:
                    # Проверяем что не превышен лимит входов на одной свече
                    if self.entries_on_current_bar < self.max_entries_per_bar:
                        # Проверяем можем ли войти снова
                        if self.should_enter_position(current_strategy_data, historical_strategy_data, historical_trend_data):
                            order = self.create_order(timestamp, current_price)
                            if self.execute_order(order):
                                self.entries_on_current_bar += 1  # Увеличиваем счетчик
                                actions.append({
                                    'action': 'open_position',
                                    'order_id': order.id,
                                    'price': current_price,
                                    'quantity': order.quantity,
                                    'timestamp': timestamp
                                })

                return actions  # Прерываем выполнение при закрытии позиции

        # ✅ Margin call проверяем на каждой execution свече
        if self.has_open_position():
            position = self.get_open_position()
            margin_call, margin_reason = self.check_margin_call(position, current_price)

            if margin_call:
                trade_info = self.close_position(current_price, timestamp, margin_reason)
                actions.append({
                    'action': 'margin_call',
                    'trade_info': trade_info,
                    'timestamp': timestamp,
                    'reason': margin_reason
                })
                return actions

        return actions
    
    def get_statistics(self) -> dict:
        """Возвращает статистику торговли"""
        # Исключаем сделки с "end_of_data" из статистики
        completed_trades = [t for t in self.trade_history if t['reason'] != 'end_of_data']
        
        if not completed_trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'average_pnl': 0,
                'max_profit': 0,
                'max_loss': 0,
                'current_balance': self.balance,
                'total_return': 0,
                'open_positions': len([t for t in self.trade_history if t['reason'] == 'end_of_data'])
            }
        
        winning_trades = [t for t in completed_trades if t['pnl'] > 0]
        losing_trades = [t for t in completed_trades if t['pnl'] <= 0]
        
        total_pnl = sum(t['pnl'] for t in completed_trades)
        
        # Рассчитываем баланс только для завершенных сделок
        completed_balance = self.initial_balance + total_pnl
        total_return = ((completed_balance - self.initial_balance) / self.initial_balance) * 100
        
        return {
            'total_trades': len(completed_trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / len(completed_trades) * 100 if completed_trades else 0,
            'total_pnl': total_pnl,
            'average_pnl': total_pnl / len(completed_trades) if completed_trades else 0,
            'max_profit': max(t['pnl'] for t in completed_trades) if completed_trades else 0,
            'max_loss': min(t['pnl'] for t in completed_trades) if completed_trades else 0,
            'current_balance': completed_balance,  # Баланс только завершенных сделок
            'total_return': total_return,
            'average_profit': np.mean([t['pnl'] for t in winning_trades]) if winning_trades else 0,
            'average_loss': np.mean([t['pnl'] for t in losing_trades]) if losing_trades else 0,
            'open_positions': len([t for t in self.trade_history if t['reason'] == 'end_of_data']),
            'actual_balance': self.balance  # Реальный баланс с незавершенными позициями
        } 