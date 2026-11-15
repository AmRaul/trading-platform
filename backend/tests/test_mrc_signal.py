from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest

from app.domain.signals.mrc import calculate_mrc
from app.domain.signals.entry_signal import evaluate_mrc_entry, closed_candles
from app.application.signals.check_entry_signal import CheckEntrySignalUseCase
from app.application.trading.close_position import ClosePositionUseCase
from app.domain.trading.position_calculator import PositionCalculator
from app.domain.trading.entities import OrderInfo
from app.services.strategy import BotState
from tests.conftest import BASE_CONFIG, make_mock_bot, make_mock_position
from tests.test_strategy_engine import _make_engine

# 1200 баров BTCUSDT 15m (Binance futures), meanline/meanrange/risk_zone посчитаны
# services/backtester/indicators.py — последний бар это сигнал risk_zone == -2
FIXTURE = Path(__file__).parent / "fixtures" / "mrc_btc_15m.csv"
SIGNAL_CFG = {
    "type": "mrc", "timeframe": "15", "mrc_length": 200, "mrc_inner_mult": 1.0,
    "mrc_outer_mult": 2.415, "mrc_gradsize": 0.5, "mrc_source": "hlc3",
    "entry_band": 2, "trend_ema_period": 200, "trend_timeframe": "D",
}


def _fixture():
    return pd.read_csv(FIXTURE)


def _candles(df):
    return df[["timestamp", "open", "high", "low", "close", "volume"]].to_dict("records")


def _trend(direction: str, n=300):
    """Дневные свечи: рост (close выше EMA) или падение (close ниже EMA)."""
    closes = np.linspace(50000, 100000, n) if direction == "up" else np.linspace(100000, 50000, n)
    day = 86_400_000
    return [{"timestamp": i * day, "open": c, "high": c, "low": c, "close": c, "volume": 1.0}
            for i, c in enumerate(closes)]


# ── MRC parity with backtester ────────────────────────────────────────────────

def test_mrc_matches_backtester():
    df = _fixture()
    mrc = calculate_mrc(df)
    assert (mrc["risk_zone"].values == df["risk_zone"].values).all()
    np.testing.assert_allclose(mrc["meanline"].values, df["meanline"].values, rtol=1e-12)
    np.testing.assert_allclose(mrc["meanrange"].values, df["meanrange"].values, rtol=1e-12)


# ── evaluate_mrc_entry ────────────────────────────────────────────────────────

def test_long_signal_in_uptrend_triggers():
    result = evaluate_mrc_entry("LONG", _candles(_fixture()), _trend("up"), SIGNAL_CFG)
    assert result.triggered
    assert result.risk_zone == -2
    assert result.trend_ok


def test_long_signal_blocked_by_downtrend():
    result = evaluate_mrc_entry("LONG", _candles(_fixture()), _trend("down"), SIGNAL_CFG)
    assert not result.triggered
    assert result.risk_zone == -2
    assert result.trend_ok is False


def test_no_trend_filter_ignores_trend_candles():
    cfg = {**SIGNAL_CFG, "trend_ema_period": None}
    result = evaluate_mrc_entry("LONG", _candles(_fixture()), None, cfg)
    assert result.triggered


def test_short_needs_positive_band():
    result = evaluate_mrc_entry("SHORT", _candles(_fixture()), _trend("down"), SIGNAL_CFG)
    assert not result.triggered


def test_no_signal_on_previous_bar():
    df = _fixture()
    prev = df.iloc[:-1]
    assert prev["risk_zone"].iloc[-1] != -2
    result = evaluate_mrc_entry("LONG", _candles(prev), _trend("up"), SIGNAL_CFG)
    assert not result.triggered


def test_not_enough_candles():
    result = evaluate_mrc_entry("LONG", _candles(_fixture().tail(50)), _trend("up"), SIGNAL_CFG)
    assert not result.triggered
    assert "мало свечей" in result.reason


def test_closed_candles_drops_forming_candle_and_sorts():
    interval = 900_000
    candles = [{"timestamp": t, "close": 1.0} for t in (2 * interval, 0, interval)]
    now = 2 * interval + 60_000  # третья свеча ещё формируется
    assert [c["timestamp"] for c in closed_candles(candles, interval, now)] == [0, interval]


@pytest.mark.asyncio
async def test_check_use_case_ignores_unclosed_candle():
    df = _fixture()
    candles = _candles(df)
    last_ts = int(df["timestamp"].iloc[-1])
    # Bybit отдаёт свечи от новой к старой, включая текущую незакрытую
    forming = {**candles[-1], "timestamp": last_ts + 900_000, "close": candles[-1]["close"] * 1.05}
    market = MagicMock()
    market.get_klines = AsyncMock(side_effect=[
        list(reversed(candles + [forming])),
        list(reversed(_trend("up"))),
    ])
    now_ms = last_ts + 900_000 + 5_000
    result = await CheckEntrySignalUseCase(market).execute("BTCUSDT", "LONG", SIGNAL_CFG, now_ms)
    assert result.triggered
    market.get_klines.assert_any_call("BTCUSDT", "15", 1000)
    market.get_klines.assert_any_call("BTCUSDT", "D", 1000)


# ── bot state transitions ─────────────────────────────────────────────────────

def _signal_config(**extra):
    return {**BASE_CONFIG, "bot_type": "dca", "tp_percent": 0.97, "entry_signal": SIGNAL_CFG, **extra}


@pytest.mark.asyncio
async def test_arm_signal_entry_sets_signal_state():
    bot = make_mock_bot(config=_signal_config(), state="IDLE")
    engine, *_ = _make_engine(bot, None, AsyncMock())
    result = await engine.arm_signal_entry()
    assert result["success"]
    assert bot.state == BotState.SIGNAL
    assert engine.current_state == BotState.SIGNAL


@pytest.mark.asyncio
async def test_arm_signal_entry_requires_signal_config():
    bot = make_mock_bot(config=dict(BASE_CONFIG), state="IDLE")
    engine, *_ = _make_engine(bot, None, AsyncMock())
    result = await engine.arm_signal_entry()
    assert not result["success"]
    assert engine.current_state == BotState.IDLE


@pytest.mark.asyncio
async def test_signal_entry_opens_position():
    bot = make_mock_bot(config=_signal_config(), state="SIGNAL")
    db = AsyncMock()
    db.add = MagicMock()
    engine, executor, *_ = _make_engine(bot, None, db)
    result = await engine.signal_entry()
    assert result["success"]
    executor.open_position.assert_awaited_once()
    assert engine.current_state == BotState.PYRAMIDING


@pytest.mark.asyncio
async def test_signal_entry_only_from_signal_state():
    bot = make_mock_bot(config=_signal_config(), state="IDLE")
    engine, executor, *_ = _make_engine(bot, None, AsyncMock())
    result = await engine.signal_entry()
    assert not result["success"]
    executor.open_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_signal_wait_returns_to_idle():
    bot = make_mock_bot(config=_signal_config(), state="SIGNAL")
    engine, *_ = _make_engine(bot, None, AsyncMock())
    result = await engine.cancel_limit_entry()
    assert result["success"]
    assert bot.state == BotState.IDLE


async def _close(config):
    bot = make_mock_bot(config=config, state="PYRAMIDING")
    pos = make_mock_position()
    calc = PositionCalculator(config)
    calc.add_order(OrderInfo(1, 50000.0, 100.0))
    executor = MagicMock()
    executor.close_position = AsyncMock(return_value={"success": True})
    publisher = MagicMock()
    publisher.publish = AsyncMock()
    db = AsyncMock()
    db.add = MagicMock()
    await ClosePositionUseCase(executor, publisher).execute(bot, pos, calc, 50500.0, "TP", db)
    return bot


@pytest.mark.asyncio
async def test_cycle_with_signal_waits_for_next_signal(monkeypatch):
    created = []
    monkeypatch.setattr("asyncio.create_task", lambda coro: created.append(coro))
    bot = await _close(_signal_config(cycle=True))
    assert bot.state == "SIGNAL"
    assert created == []  # не переоткрывается сразу


@pytest.mark.asyncio
async def test_signal_without_cycle_goes_idle():
    bot = await _close(_signal_config(cycle=False))
    assert bot.state == "IDLE"
