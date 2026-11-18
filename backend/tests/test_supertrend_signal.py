from pathlib import Path
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from app.domain.signals.entry_signal import evaluate_entry, evaluate_supertrend_entry
from app.domain.signals.supertrend import supertrend_direction
from app.application.signals.check_entry_signal import CheckEntrySignalUseCase
from app.schemas.bot import EntrySignalConfig, StrategyConfig

# SOLUSDT (Binance futures): 1000 закрытых 15m и 1000 закрытых 4h свечей на момент
# шорт-сигнала исследования trend_pullback_pyramid (2026-08-07 17:00, закрытие 17:15)
FIXTURES = Path(__file__).parent / "fixtures"
CFG = {"type": "supertrend", "timeframe": "15", "st_period": 10, "st_mult": 3.0,
       "trend_ema_period": 200, "trend_ema_fast": 50, "trend_timeframe": "240"}


def _load(name):
    return pd.read_csv(FIXTURES / name).to_dict("records")


def _flat(n=300, start=100.0, end=100.0, step_ms=900_000):
    return [{"timestamp": i * step_ms, "open": c, "high": c * 1.001, "low": c * 0.999, "close": c, "volume": 1.0}
            for i, c in enumerate(np.linspace(start, end, n))]


def test_short_signal_on_real_flip():
    r = evaluate_supertrend_entry("SHORT", _load("st_sol_15m.csv"), _load("st_sol_4h.csv"), CFG)
    assert r.triggered and r.trend_ok and r.reason == "сигнал"


def test_long_not_triggered_on_short_flip():
    r = evaluate_supertrend_entry("LONG", _load("st_sol_15m.csv"), _load("st_sol_4h.csv"), CFG)
    assert not r.triggered


def test_no_signal_one_candle_later():
    """Разворот засчитывается только на свече, где он произошёл."""
    s = _load("st_sol_15m.csv")
    nxt = dict(s[-1], timestamp=s[-1]["timestamp"] + 900_000)
    r = evaluate_supertrend_entry("SHORT", s[1:] + [nxt], _load("st_sol_4h.csv"), CFG)
    assert not r.triggered


def test_regime_blocks_short_in_uptrend():
    up = _flat(300, 50, 100, step_ms=14_400_000)
    r = evaluate_supertrend_entry("SHORT", _load("st_sol_15m.csv"), up, CFG)
    assert not r.triggered and r.reason == "тренд против направления"


def test_fast_ema_required_for_regime():
    """close ниже EMA200, но EMA50 ещё выше EMA200 — режима нет."""
    closes = list(np.linspace(100, 200, 400)) + list(np.linspace(200, 150, 20))
    trend = [{"timestamp": i * 14_400_000, "open": c, "high": c, "low": c, "close": c, "volume": 1.0}
             for i, c in enumerate(closes)]
    s = pd.Series(closes)
    assert s.iloc[-1] < s.ewm(span=200, adjust=False).mean().iloc[-1]
    assert s.ewm(span=50, adjust=False).mean().iloc[-1] > s.ewm(span=200, adjust=False).mean().iloc[-1]
    signal = _load("st_sol_15m.csv")
    assert evaluate_supertrend_entry("SHORT", signal, trend, {**CFG, "trend_ema_fast": None}).triggered
    assert not evaluate_supertrend_entry("SHORT", signal, trend, CFG).triggered


def test_not_enough_trend_candles():
    r = evaluate_supertrend_entry("SHORT", _load("st_sol_15m.csv"), _load("st_sol_4h.csv")[:100], CFG)
    assert not r.triggered and "мало свечей" in r.reason


def test_warmup_is_zero():
    d = supertrend_direction(pd.DataFrame(_flat(50)), period=10)
    assert (d[:30] == 0).all()


def test_evaluate_entry_dispatches_by_type():
    r = evaluate_entry("SHORT", _load("st_sol_15m.csv"), _load("st_sol_4h.csv"), CFG)
    assert r.triggered and r.risk_zone is None


@pytest.mark.asyncio
async def test_use_case_fetches_4h_trend():
    market = AsyncMock()
    market.get_klines = AsyncMock(side_effect=[_load("st_sol_15m.csv"), _load("st_sol_4h.csv")])
    now = _load("st_sol_15m.csv")[-1]["timestamp"] + 900_000
    r = await CheckEntrySignalUseCase(market).execute("SOLUSDT", "SHORT", CFG, now)
    assert r.triggered
    assert [c.args[1] for c in market.get_klines.await_args_list] == ["15", "240"]


def test_schema_accepts_supertrend():
    cfg = StrategyConfig(bot_type="pyramiding", order_count=4, entry_size_usdt=250, step_percent=0.5,
                         pyramiding_multiplier=1.0, sl_initial=2, sl_after_order3=2,
                         sl_breakeven_on_order2=False, use_trailing=True, trailing_percent=8.1,
                         tp_percent=100, cycle=True, entry_signal=EntrySignalConfig(**CFG))
    assert cfg.entry_signal.type == "supertrend" and cfg.entry_signal.trend_ema_fast == 50
    with pytest.raises(ValueError):
        EntrySignalConfig(**{**CFG, "type": "rsi"})


def test_result_fields_are_plain_python():
    """numpy.bool_ в triggered ронял /api/analytics/bots-health (FastAPI не сериализует)."""
    import json
    from dataclasses import asdict
    s, t = _load("st_sol_15m.csv"), _load("st_sol_4h.csv")
    for side in ("SHORT", "LONG"):  # сигнал и «разворота нет»
        r = evaluate_supertrend_entry(side, s, t, CFG)
        assert type(r.triggered) is bool and type(r.trend_ok) is bool
        json.dumps(asdict(r))
