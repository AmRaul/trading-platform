"""Donchian 20/10: вход по пробою максимума 20 дневок, выход по пробою минимума 10 дневок —
как research/long_trend_classic.py V2 (сверка на истории — research/verify_donchian_live.py)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.signals.entry_signal import (
    evaluate_donchian_entry, evaluate_donchian_exit, evaluate_entry, has_signal_exit,
)
from app.application.signals.check_entry_signal import CheckEntrySignalUseCase
from app.schemas.bot import EntrySignalConfig, StrategyConfig

CFG = {"type": "donchian", "timeframe": "60", "donchian_entry_days": 20, "donchian_exit_days": 10}
DAY = 86_400_000


def _days(highs, lows=None):
    lows = lows or [h - 10 for h in highs]
    return [{"timestamp": i * DAY, "open": h - 5, "high": h, "low": l, "close": h - 5, "volume": 1.0}
            for i, (h, l) in enumerate(zip(highs, lows))]


def _hour(close):
    return [{"timestamp": 0, "open": close, "high": close, "low": close, "close": close, "volume": 1.0}]


def test_entry_above_20_day_high():
    daily = _days([100.0] * 19 + [120.0] + [110.0] * 5)  # максимум последних 20 — 120
    assert evaluate_donchian_entry("LONG", _hour(121), daily, CFG).triggered
    r = evaluate_donchian_entry("LONG", _hour(120), daily, CFG)
    assert not r.triggered and r.trend_ema == 120  # нужно строго выше


def test_entry_window_is_last_20_days_only():
    daily = _days([200.0] + [100.0] * 20)  # 200 был 21 день назад — вне окна
    assert evaluate_donchian_entry("LONG", _hour(101), daily, CFG).triggered


def test_exit_below_10_day_low():
    daily = _days([100.0] * 30, lows=[50.0] * 20 + [80.0] * 10)  # минимум последних 10 — 80
    assert evaluate_donchian_exit("LONG", _hour(79.9), daily, CFG).triggered
    assert not evaluate_donchian_exit("LONG", _hour(80), daily, CFG).triggered


def test_short_mirror():
    daily = _days([100.0] * 25, lows=[90.0] * 25)
    assert evaluate_donchian_entry("SHORT", _hour(89), daily, CFG).triggered
    assert evaluate_donchian_exit("SHORT", _hour(101), daily, CFG).triggered


def test_not_enough_days():
    r = evaluate_donchian_entry("LONG", _hour(1000), _days([100.0] * 5), CFG)
    assert not r.triggered and "мало" in r.reason


def test_dispatch_and_exit_flag():
    daily = _days([100.0] * 25)
    assert evaluate_entry("LONG", _hour(101), daily, CFG).triggered
    assert has_signal_exit(CFG) and not has_signal_exit({"type": "mrc"}) and not has_signal_exit(None)


def test_schema_accepts_donchian_without_trend_filter():
    cfg = StrategyConfig(bot_type="pyramiding", order_count=1, entry_size_usdt=1000, step_percent=1.0,
                         sl_initial=None, use_trailing=False, tp_percent=100,
                         entry_signal=EntrySignalConfig(**CFG, trend_ema_period=None))
    assert cfg.entry_signal.type == "donchian" and cfg.entry_signal.donchian_exit_days == 10


@pytest.mark.asyncio
async def test_use_case_reads_closed_daily_candles():
    now = 30 * DAY + 3_600_000 + 5_000  # 01:00:05 UTC 31-го дня: последняя дневка ещё не закрыта
    daily = _days([100.0] * 31)  # 31-я (индекс 30) открыта в now-1ч — отбрасывается
    daily[30]["high"] = 1000.0
    hours = [{"timestamp": now - 5_000 - 3_600_000, "open": 101, "high": 101, "low": 101, "close": 101, "volume": 1}]
    md = MagicMock()
    md.get_klines = AsyncMock(side_effect=lambda s, tf, n: daily if tf == "D" else hours)
    uc = CheckEntrySignalUseCase(md)
    r = await uc.execute("BTCUSDT", "LONG", CFG, now)
    assert r.triggered  # открытая дневка с high 1000 в канал не попала
    x = await uc.execute_exit("BTCUSDT", "LONG", CFG, now)
    assert not x.triggered
