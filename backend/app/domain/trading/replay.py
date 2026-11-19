"""
Повтор позиции на свечах — для сверки живой/бумажной сделки с бэктестом.

Та же логика, что у живого бота на каждом тике (StrategyEngine.on_price_update):
стоп → тейк → добор (пирамида или DCA) → подтяжка стопа; после добора стоп
пересчитывается заново (AddPyramidingOrderUseCase), иначе — только в сторону прибыли
(HandlePriceUpdateUseCase). Вместо тиков цена идёт по OHLC: open→low→high→close у
растущей свечи, open→high→low→close у падающей — как в бэктестере. На open (гэп)
исполнение по цене open, внутри свечи — по уровню.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.domain.trading.entities import OrderInfo
from app.domain.trading.position_calculator import PositionCalculator


@dataclass
class ReplayOrder:
    number: int
    time_ms: int
    price: float
    size: float


@dataclass
class ReplayResult:
    orders: List[ReplayOrder] = field(default_factory=list)
    exit_time_ms: Optional[int] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # SL_HIT | TRAILING_STOP | TP_HIT; None — позиция ещё открыта
    current_sl: Optional[float] = None

    @property
    def is_open(self) -> bool:
        return self.exit_reason is None


def _price_path(c: Dict) -> List[float]:
    if c["close"] >= c["open"]:
        return [c["open"], c["low"], c["high"], c["close"]]
    return [c["open"], c["high"], c["low"], c["close"]]


def _add_level(calc: PositionCalculator, side: str) -> float:
    """Цена, на которой срабатывает добор (как should_add_*_order живого бота)."""
    if calc.is_dca():
        return calc.next_dca_price(side)
    s = 1 if side == "LONG" else -1
    step = calc.config["step_percent"] / 100 - calc.config.get("order_trigger_buffer_pct", 0.05) / 100
    return calc.get_last_order_price() * (1 + s * step)


def _should_add(calc: PositionCalculator, side: str, price: float) -> bool:
    if calc.is_dca():
        return calc.should_add_dca_order(side, price)
    return calc.should_add_order(side, price, calc.get_last_order_price())


def replay_position(
    config: Dict,
    side: str,
    entry_price: float,
    entry_time_ms: int,
    candles: List[Dict],
    interval_ms: int = 60_000,
    trailing_enabled: bool = True,
) -> ReplayResult:
    """candles — по возрастанию времени (timestamp — открытие свечи, мс); свечи,
    закрывшиеся до входа, пропускаются. Свеча входа проигрывается целиком: её часть
    до входа — секунды при входе на закрытии сигнальной свечи."""
    s = 1 if side == "LONG" else -1
    calc = PositionCalculator(config)
    first_size = config["entry_size_usdt"]
    calc.add_order(OrderInfo(1, entry_price, first_size))
    res = ReplayResult(orders=[ReplayOrder(1, entry_time_ms, entry_price, first_size)])
    sl, _ = calc.calculate_stop_loss(side, calc.orders, entry_price, trailing_enabled=trailing_enabled)

    for c in candles:
        if c["timestamp"] + interval_ms <= entry_time_ms:
            continue
        for k, p in enumerate(_price_path(c)):
            gap = k == 0
            # 1. стоп
            if calc.is_stop_loss_hit(side, p, sl):
                _, sl_type = calc.calculate_stop_loss(side, calc.orders, p, trailing_enabled=trailing_enabled)
                res.exit_reason = "TRAILING_STOP" if sl_type == "trailing" else "SL_HIT"
                res.exit_price, res.exit_time_ms, res.current_sl = (p if gap else sl), c["timestamp"], sl
                return res
            # 2. тейк
            if calc.is_take_profit_hit(side, p):
                tp = calc.take_profit_price(side)
                res.exit_reason = "TP_HIT"
                res.exit_price, res.exit_time_ms, res.current_sl = (p if gap else tp), c["timestamp"], sl
                return res
            # 3. добор (за одну точку пути цена может пройти несколько уровней)
            added = False
            while _should_add(calc, side, p):
                fill = p if gap else _add_level(calc, side)
                size = calc.calculate_next_order_size()
                calc.add_order(OrderInfo(len(calc.orders) + 1, fill, size))
                res.orders.append(ReplayOrder(len(calc.orders), c["timestamp"], fill, size))
                sl, _ = calc.calculate_stop_loss(side, calc.orders, fill, trailing_enabled=trailing_enabled)
                added = True
            # 4. подтяжка стопа — только в сторону прибыли
            if not added:
                new_sl, _ = calc.calculate_stop_loss(side, calc.orders, p, trailing_enabled=trailing_enabled)
                if sl == 0 or (new_sl - sl) * s > 0:
                    sl = new_sl
    res.current_sl = sl
    return res
