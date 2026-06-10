from dataclasses import dataclass
from typing import List, Dict, Optional

from app.domain.trend.ema_calculator import ema21_series

# Откат считается если цена в пределах X% от EMA21
PULLBACK_TOLERANCE_PCT = 5.0


@dataclass
class TrendSignal:
    symbol: str
    side: str            # LONG / SHORT
    entry_price: float
    stop_price: float
    stop_pct: float
    ema21_4h: float
    ema21_1h: float
    trend_4h: str        # UP / DOWN
    pullback_1h: bool
    trigger_15m: bool


def _closes(candles: List[Dict]) -> List[float]:
    return [float(c["close"]) for c in candles]


def _is_near_ema(price: float, ema_val: float, tolerance_pct: float) -> bool:
    if ema_val == 0:
        return False
    return abs(price - ema_val) / ema_val * 100 <= tolerance_pct


class TrendDetector:
    """
    Детектирует 4H/1H/15m сигналы по тренду:
    - 4H: цена > EMA21 и EMA21 растёт → тренд UP
    - 1H: цена откатила к EMA21 (±2%)
    - 15m: последняя свеча закрылась выше хая предыдущей (триггер)
    SHORT: зеркальная логика
    """

    def detect(
        self,
        symbol: str,
        candles_4h: List[Dict],
        candles_1h: List[Dict],
        candles_15m: List[Dict],
    ) -> Optional[TrendSignal]:
        if len(candles_4h) < 25 or len(candles_1h) < 25 or len(candles_15m) < 3:
            return None

        closes_4h = _closes(candles_4h)
        closes_1h = _closes(candles_1h)

        ema21_4h_series = ema21_series(closes_4h)
        ema21_1h_series = ema21_series(closes_1h)

        if len(ema21_4h_series) < 2 or len(ema21_1h_series) < 2:
            return None

        ema_4h_now = ema21_4h_series[-1]
        ema_4h_prev = ema21_4h_series[-2]
        ema_1h_now = ema21_1h_series[-1]

        last_close_4h = closes_4h[-1]
        last_close_1h = closes_1h[-1]

        last_candle_15m = candles_15m[-1]
        prev_candle_15m = candles_15m[-2]

        last_close_15m = float(last_candle_15m["close"])
        prev_high_15m = float(prev_candle_15m["high"])
        trigger_low_15m = float(last_candle_15m["low"])

        # --- LONG ---
        # Тренд: цена выше EMA21 на 4H (не требуем строгого роста EMA — достаточно направления)
        trend_up = last_close_4h > ema_4h_now
        # Откат: 1H цена близко к EMA21 (±5%) или ниже неё но разворачивается
        pullback_long = _is_near_ema(last_close_1h, ema_1h_now, PULLBACK_TOLERANCE_PCT) or last_close_1h <= ema_1h_now * 1.01
        # Триггер: бычья 15m свеча (close > open) или пробой хая предыдущей
        trigger_long = last_close_15m > float(last_candle_15m["open"]) or last_close_15m > prev_high_15m

        if trend_up and pullback_long and trigger_long:
            entry = last_close_15m
            stop = trigger_low_15m
            stop_pct = round((entry - stop) / entry * 100, 2) if entry > 0 else 0
            return TrendSignal(
                symbol=symbol,
                side="LONG",
                entry_price=entry,
                stop_price=stop,
                stop_pct=stop_pct,
                ema21_4h=round(ema_4h_now, 6),
                ema21_1h=round(ema_1h_now, 6),
                trend_4h="UP",
                pullback_1h=True,
                trigger_15m=True,
            )

        # --- SHORT ---
        trend_down = last_close_4h < ema_4h_now
        pullback_short = _is_near_ema(last_close_1h, ema_1h_now, PULLBACK_TOLERANCE_PCT) or last_close_1h >= ema_1h_now * 0.99
        trigger_short = last_close_15m < float(last_candle_15m["open"]) or last_close_15m < float(prev_candle_15m["low"])

        if trend_down and pullback_short and trigger_short:
            entry = last_close_15m
            stop = float(last_candle_15m["high"])
            stop_pct = round((stop - entry) / entry * 100, 2) if entry > 0 else 0
            return TrendSignal(
                symbol=symbol,
                side="SHORT",
                entry_price=entry,
                stop_price=stop,
                stop_pct=stop_pct,
                ema21_4h=round(ema_4h_now, 6),
                ema21_1h=round(ema_1h_now, 6),
                trend_4h="DOWN",
                pullback_1h=True,
                trigger_15m=True,
            )

        return None
