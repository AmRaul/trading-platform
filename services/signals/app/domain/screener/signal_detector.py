from typing import List
from dataclasses import dataclass
from app.domain.screener.entities import ScreenerCandidate


@dataclass
class Signal:
    symbol: str
    side: str           # LONG / SHORT / WATCH
    strategy: str       # MOMENTUM / REVERSAL / BREAKOUT
    entry_price: float
    vol_1h_pct: float
    price_range_pct: float
    avg_candle_size_pct: float
    price_change_24h_pct: float
    funding_rate: float
    open_interest: float


VOL_1H_MIN = 15.0
VOLATILITY_MIN = 0.3

# MOMENTUM: входим по тренду — ужесточённые пороги чтобы не входить в каждый памп
MOMENTUM_LONG_RANGE_MIN = 65.0
MOMENTUM_LONG_CHANGE_MIN = 15.0
MOMENTUM_SHORT_RANGE_MAX = 20.0
MOMENTUM_SHORT_CHANGE_MAX = -20.0

# REVERSAL: входим против движения у экстремума
REVERSAL_LONG_RANGE_MAX = 25.0
REVERSAL_LONG_CHANGE_MAX = -10.0
REVERSAL_SHORT_RANGE_MIN = 75.0
REVERSAL_SHORT_CHANGE_MIN = 10.0

# BREAKOUT: флэт с аномальным объёмом, ждём пробой
BREAKOUT_RANGE_MIN = 30.0   # посередине диапазона
BREAKOUT_RANGE_MAX = 70.0
BREAKOUT_CHANGE_MAX = 5.0   # change за 24h в пределах ±5% — нет тренда
BREAKOUT_CHANGE_MIN = -5.0


class SignalDetector:
    """Detects MOMENTUM, REVERSAL and BREAKOUT signals from screener candidates."""

    def detect_all(self, candidate: ScreenerCandidate, vol_1h_pct: float) -> List[Signal]:
        if candidate.avg_candle_size_pct < VOLATILITY_MIN:
            return []
        if vol_1h_pct < VOL_1H_MIN:
            return []
        if candidate.price_range_pct is None:
            return []

        signals = []

        # MOMENTUM
        if (candidate.price_range_pct > MOMENTUM_LONG_RANGE_MIN
                and candidate.price_change_24h_pct > MOMENTUM_LONG_CHANGE_MIN):
            signals.append(self._make(candidate, vol_1h_pct, "LONG", "MOMENTUM"))
        elif (candidate.price_range_pct < MOMENTUM_SHORT_RANGE_MAX
              and candidate.price_change_24h_pct < MOMENTUM_SHORT_CHANGE_MAX):
            signals.append(self._make(candidate, vol_1h_pct, "SHORT", "MOMENTUM"))

        # REVERSAL
        if (candidate.price_range_pct < REVERSAL_LONG_RANGE_MAX
                and candidate.price_change_24h_pct < REVERSAL_LONG_CHANGE_MAX):
            signals.append(self._make(candidate, vol_1h_pct, "LONG", "REVERSAL"))
        elif (candidate.price_range_pct > REVERSAL_SHORT_RANGE_MIN
              and candidate.price_change_24h_pct > REVERSAL_SHORT_CHANGE_MIN):
            signals.append(self._make(candidate, vol_1h_pct, "SHORT", "REVERSAL"))

        # BREAKOUT — флэт с аномальным объёмом, направление неизвестно
        if (BREAKOUT_RANGE_MIN < candidate.price_range_pct < BREAKOUT_RANGE_MAX
                and BREAKOUT_CHANGE_MIN < candidate.price_change_24h_pct < BREAKOUT_CHANGE_MAX):
            # Фиксируем как WATCH — не лонг и не шорт, просто наблюдение
            # PnL будет считаться нейтрально (как LONG для справки)
            signals.append(self._make(candidate, vol_1h_pct, "LONG", "BREAKOUT"))

        return signals

    def _make(self, candidate: ScreenerCandidate, vol_1h_pct: float, side: str, strategy: str) -> Signal:
        return Signal(
            symbol=candidate.symbol,
            side=side,
            strategy=strategy,
            entry_price=candidate.last_price,
            vol_1h_pct=round(vol_1h_pct, 2),
            price_range_pct=candidate.price_range_pct,
            avg_candle_size_pct=candidate.avg_candle_size_pct,
            price_change_24h_pct=candidate.price_change_24h_pct,
            funding_rate=candidate.funding_rate,
            open_interest=candidate.open_interest,
        )
