"""Аналитика для MCP: рыночный контекст и проверка «живы ли боты»."""
import pandas as pd
import pytest

from app.application.monitoring.bots_health import assess_bot
from app.domain.market.context import build_market_context

DAY = 86_400_000
MIN = 60_000


def _candles(closes, rng=1.0, newest_first=True):
    rows = [{"timestamp": i * DAY, "open": c, "high": c + rng, "low": c - rng, "close": c, "volume": 100.0 + i}
            for i, c in enumerate(closes)]
    return rows[::-1] if newest_first else rows


def test_uptrend_regime_and_indicators():
    closes = [100 + i for i in range(450)]
    ctx = build_market_context(_candles(closes), "D", bars=30)
    assert ctx["regime"] == "up"
    assert ctx["price"] == 549
    assert ctx["rsi14"] == 100.0  # только рост
    assert ctx["ema200"]["reliable"] is True
    s = pd.Series(closes, dtype=float)
    assert ctx["ema50"]["value"] == pytest.approx(s.ewm(span=50, adjust=False).mean().iloc[-1], rel=1e-6)
    assert len(ctx["candles"]["rows"]) == 30
    assert ctx["candles"]["rows"][-1][0] == "1971-03-26"  # от старой к новой, хотя на вход — от новой
    assert ctx["window_extremes"]["high"] == 550  # close + rng


def test_downtrend_regime():
    ctx = build_market_context(_candles([1000 - i for i in range(450)]), "240", bars=20)
    assert ctx["regime"] == "down"
    assert ctx["rsi14"] == pytest.approx(0.0, abs=1e-6)
    assert ctx["ema20"]["distance_pct"] < 0


def test_atr_constant_range():
    # high-low = 2, закрытия не меняются → TR = 2, ATR = 2
    ctx = build_market_context(_candles([50.0] * 300), "D", bars=10)
    assert ctx["atr14"] == pytest.approx(2.0)
    assert ctx["atr14_pct"] == pytest.approx(4.0)
    assert ctx["regime"] == "mixed"


def test_short_history_flags_unreliable_ema200():
    ctx = build_market_context(_candles([100 + i % 5 for i in range(120)]), "D")
    assert ctx["ema200"]["reliable"] is False
    assert ctx["history_bars"] == 120


def test_too_few_candles():
    assert "error" in build_market_context(_candles([1.0]), "D")


# ── bots health ──────────────────────────────────────────────────────────────

SIGNAL_CFG = {"cycle": True, "entry_signal": {"type": "supertrend", "timeframe": "15"}}
NOW = 1_000 * DAY


def _assess(**kw):
    base = dict(state="SIGNAL", config=SIGNAL_CFG, has_open_position=False, registered_for_prices=False,
                scheduler_running=True, scheduler_started_ms=NOW - 10 * DAY,
                last_check={"checked_at_ms": NOW - 5 * MIN, "reason": "нет разворота"}, now_ms=NOW)
    return assess_bot(**{**base, **kw})


def test_signal_bot_checked_recently_is_ok():
    r = _assess()
    assert r["status"] == "ok" and "нет разворота" in r["notes"][0]


def test_signal_bot_stale_check():
    r = _assess(last_check={"checked_at_ms": NOW - 40 * MIN, "reason": ""})
    assert r["status"] == "problem" and "40 мин" in r["issues"][0]


def test_signal_bot_scheduler_down():
    assert _assess(scheduler_running=False)["status"] == "problem"


def test_signal_bot_after_restart_not_yet_checked_is_ok():
    r = _assess(last_check=None, scheduler_started_ms=NOW - 5 * MIN)
    assert r["status"] == "ok"


def test_signal_bot_never_checked_long_after_restart():
    assert _assess(last_check=None)["status"] == "problem"


def test_pyramiding_bot_not_in_price_stream():
    r = _assess(state="PYRAMIDING", has_open_position=True, registered_for_prices=False)
    assert r["status"] == "problem" and "поток цен" in r["issues"][0]


def test_pyramiding_bot_healthy():
    assert _assess(state="PYRAMIDING", has_open_position=True, registered_for_prices=True)["status"] == "ok"


def test_pyramiding_without_position():
    r = _assess(state="PYRAMIDING", has_open_position=False, registered_for_prices=True)
    assert r["status"] == "problem"


def test_cycle_signal_bot_dropped_to_idle():
    r = _assess(state="IDLE")
    assert r["status"] == "problem" and "IDLE" in r["issues"][0]


def test_plain_idle_bot_is_ok():
    assert _assess(state="IDLE", config={"cycle": False})["status"] == "ok"


def test_volume_ratio_uses_last_closed_candle():
    rows = _candles([100.0] * 60, newest_first=False)
    for r in rows:
        r["volume"] = 100.0
    rows[-2]["volume"] = 300.0  # последняя закрытая — всплеск
    rows[-1]["volume"] = 5.0    # текущая, только началась
    ctx = build_market_context(rows, "D")
    assert ctx["last_closed_volume_vs_avg20"] == pytest.approx(3.0)
