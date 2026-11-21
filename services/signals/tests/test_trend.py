"""Тренд 4H/1H/15m: EMA21 и правила LONG/SHORT."""
import pytest

from app.domain.trend.ema_calculator import ema, ema21
from app.domain.trend.trend_detector import TrendDetector


def test_ema_basics():
    assert ema([1, 2], 3) == []
    assert ema21([5.0] * 30) == pytest.approx(5.0)
    out = ema([1, 2, 3, 4], 3)
    assert out[0] == 1 and out[1] == pytest.approx(1.5) and out[-1] == pytest.approx(3.125)


def bars(closes, spread=0.5):
    return [{"open": c, "high": c + spread, "low": c - spread, "close": c} for c in closes]


def k15(prev, last):
    """15m свечи: (open, high, low, close)."""
    return [{"open": o, "high": h, "low": l, "close": c} for o, h, l, c in ((100, 101, 99, 100), prev, last)]


UP_4H = bars([80 + i for i in range(40)])          # цена над EMA21
DOWN_4H = bars([120 - i for i in range(40)])
NEAR_1H = bars([100.0] * 40)                         # у EMA21 — откат


def test_long_on_uptrend_pullback_and_bullish_15m():
    s = TrendDetector().detect("X", UP_4H, NEAR_1H, k15((100, 101, 99, 100), (100, 102, 99.5, 101.5)))
    assert s.side == "LONG" and s.entry_price == 101.5 and s.stop_price == 99.5 and s.stop_pct == 1.97


def test_short_on_downtrend_and_bearish_15m():
    s = TrendDetector().detect("X", DOWN_4H, NEAR_1H, k15((100, 101, 99, 100), (100, 100.5, 98, 98.5)))
    assert s.side == "SHORT" and s.stop_price == 100.5 and s.stop_pct == 2.03


def test_no_signal_against_trigger_or_short_history():
    d = TrendDetector()
    assert d.detect("X", UP_4H, NEAR_1H, k15((100, 101, 99, 100), (100, 100.5, 98, 98.5))) is None  # медвежья 15m в аптренде
    assert d.detect("X", UP_4H[:20], NEAR_1H, k15((100, 101, 99, 100), (100, 102, 99.5, 101.5))) is None
