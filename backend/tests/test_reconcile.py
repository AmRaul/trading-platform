"""Сверка позиции с бэктестом: replay_position, compare_with_replay, ReconcilePositionUseCase."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from app.application.monitoring.bots_health import assess_bot
from app.application.monitoring.reconcile_position import ReconcilePositionUseCase
from app.domain.ready_strategies.catalog import get_strategy
from app.domain.trading.reconcile import compare_with_replay
from app.domain.trading.replay import ReplayOrder, ReplayResult, replay_position

M = 60_000
T0 = 1_700_000_000_000 - 1_700_000_000_000 % (15 * M)


def short_cfg(variant="conservative", **over):
    s = get_strategy("alt-short-pyramid-5")
    v = next(v for v in s.variants if v.key == variant)
    return {**s.variant_preset(v, s.legs[3]), **over}  # ETH: трейлинг 5%


def candle(i, o, h, l, c):
    return {"timestamp": T0 + i * M, "open": o, "high": h, "low": l, "close": c, "volume": 1.0}


def test_short_full_grid_then_stop():
    cfg = short_cfg()
    r = replay_position(cfg, "SHORT", 100.0, T0, [
        candle(0, 100, 100.1, 98.4, 98.5),   # падение: все 3 добора
        candle(1, 98.5, 101.5, 98.4, 101.0),  # разворот выше стопа avg+2%
    ])
    assert [o.number for o in r.orders] == [1, 2, 3, 4]
    assert r.orders[1].price == pytest.approx(100 * (1 - 0.0045))
    avg = sum(o.price for o in r.orders) / 4
    assert r.exit_reason == "SL_HIT"
    assert r.exit_price == pytest.approx(avg * 1.02)
    assert r.exit_time_ms == T0 + M


def test_short_tp6_after_full_grid():
    cfg = short_cfg("conservative_tp6")
    r = replay_position(cfg, "SHORT", 100.0, T0, [
        candle(0, 100, 100.1, 98.4, 98.5),
        candle(1, 98.5, 98.6, 92.0, 92.5),
    ])
    avg = sum(o.price for o in r.orders) / 4
    assert r.exit_reason == "TP_HIT" and r.exit_price == pytest.approx(avg * 0.94)


def test_short_trailing_after_big_drop():
    cfg = short_cfg()
    r = replay_position(cfg, "SHORT", 100.0, T0, [
        candle(0, 100, 100.1, 98.4, 98.5),
        candle(1, 98.5, 98.6, 90.0, 90.2),   # трейлинг 5%: стоп 94.5
        candle(2, 90.2, 95.0, 90.1, 94.9),
    ])
    assert r.exit_reason == "TRAILING_STOP"
    assert r.exit_price == pytest.approx(90.0 * 1.05)


def test_open_position_keeps_current_sl():
    r = replay_position(short_cfg(), "SHORT", 100.0, T0, [candle(0, 100, 100.2, 99.7, 99.8)])
    assert r.is_open and len(r.orders) == 1 and r.current_sl == pytest.approx(102.0)


def test_candles_before_entry_skipped():
    r = replay_position(short_cfg(), "SHORT", 100.0, T0 + 5 * M, [
        candle(0, 100, 110, 90, 100),        # закрылась до входа — иначе был бы стоп
        candle(5, 100, 100.2, 99.7, 99.8),
    ])
    assert r.is_open


def test_dca_long_adds_on_drop():
    s = get_strategy("mrc-dca-btc-15m-long")
    cfg = s.variant_preset(s.variants[0])
    r = replay_position(cfg, "LONG", 100.0, T0, [candle(0, 100, 100.1, 98.3, 98.5)])
    assert len(r.orders) == 2
    assert r.orders[1].price == pytest.approx(100 * (1 - cfg["step_percent"] / 100))


# ── compare ──────────────────────────────────────────────────────────────────

def _replay(prices, exit_=None):
    r = ReplayResult(orders=[ReplayOrder(i + 1, T0 + i * M, p, 250) for i, p in enumerate(prices)])
    if exit_:
        r.exit_reason, r.exit_price, r.exit_time_ms = exit_
    return r


def _live(prices):
    return [{"number": i + 1, "price": p, "time_ms": T0 + i * M} for i, p in enumerate(prices)]


def test_compare_match():
    out = compare_with_replay(_live([100, 99.55]), {"time_ms": T0 + 5 * M, "price": 101.6, "reason": "SL_HIT"},
                              _replay([100, 99.55], ("SL_HIT", 101.58, T0 + 5 * M)))
    assert out["verdict"] == "match" and not out["issues"] and not out["drift"]


def test_compare_price_drift():
    out = compare_with_replay(_live([100, 99.2]), None, _replay([100, 99.55]))
    assert out["verdict"] == "price_drift" and "ордер 2" in out["drift"][0]


def test_compare_mismatch_order_count():
    out = compare_with_replay(_live([100]), {"time_ms": T0, "price": 102, "reason": "SL_HIT"},
                              _replay([100, 99.55], ("SL_HIT", 101.5, T0 + M)))
    assert out["verdict"] == "mismatch" and "ордеров" in out["issues"][0]


def test_compare_mismatch_exit_reason():
    out = compare_with_replay(_live([100]), {"time_ms": T0, "price": 102, "reason": "SL_HIT"},
                              _replay([100], ("TP_HIT", 94, T0)))
    assert out["verdict"] == "mismatch"


def test_compare_bot_open_replay_closed():
    out = compare_with_replay(_live([100]), None, _replay([100], ("SL_HIT", 102, T0 + M)))
    assert out["verdict"] == "mismatch" and "держит" in out["issues"][0]


def test_compare_manual_close():
    out = compare_with_replay(_live([100]), {"time_ms": T0 + 3 * M, "price": 99, "reason": "MANUAL_CLOSE"},
                              _replay([100]))
    assert out["verdict"] == "manual"


# ── use case на реальных свечах SOL (сигнал шорта из исследования) ───────────

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return pd.read_csv(FIXTURES / name).to_dict("records")


class FakeMarket:
    def __init__(self, minutes):
        self.minutes = minutes
        self.calls = []

    async def get_klines(self, symbol, interval, limit, end_ms=None):
        self.calls.append((interval, end_ms))
        data = _load("st_sol_15m.csv" if interval == "15" else "st_sol_4h.csv")
        return [c for c in data if end_ms is None or c["timestamp"] <= end_ms][-limit:]

    async def get_klines_range(self, symbol, interval, start_ms, end_ms):
        return [c for c in self.minutes if start_ms <= c["timestamp"] <= end_ms]


def _dt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


@pytest.mark.asyncio
async def test_use_case_signal_and_full_cycle():
    s15 = _load("st_sol_15m.csv")
    signal_close = s15[-1]["timestamp"] + 15 * M
    entry_ms = signal_close + 6_000
    p0 = s15[-1]["close"]
    minutes = [{"timestamp": signal_close + i * M, "open": o, "high": h, "low": l, "close": c, "volume": 1}
               for i, (o, h, l, c) in enumerate([
                   (p0, p0 * 1.001, p0 * 0.984, p0 * 0.985),
                   (p0 * 0.985, p0 * 1.02, p0 * 0.984, p0 * 1.01)])]
    cfg = {**short_cfg(), "entry_signal": {"type": "supertrend", "timeframe": "15", "st_period": 10,
                                           "st_mult": 3.0, "trend_ema_period": 200, "trend_ema_fast": 50,
                                           "trend_timeframe": "240"}}
    replay = replay_position(cfg, "SHORT", p0, entry_ms, minutes)
    bot = SimpleNamespace(id=2, symbol="SOLUSDT", side="SHORT", exchange="paper", config=cfg)
    position = SimpleNamespace(id=3, opened_at=_dt(entry_ms), is_bot_managed=True, trailing_enabled=True,
                               current_sl=None)
    orders = [SimpleNamespace(order_number=o.number, price=o.price, status="FILLED",
                              filled_at=_dt(max(o.time_ms, entry_ms)), created_at=None) for o in replay.orders]
    trade = SimpleNamespace(closed_at=_dt(replay.exit_time_ms + 30_000), exit_price=replay.exit_price * 1.0003,
                            exit_reason=replay.exit_reason)

    market = FakeMarket(minutes)
    out = await ReconcilePositionUseCase(market).execute(bot=bot, position=position, orders=orders, trade=trade)
    assert out["entry_signal"]["triggered"] is True
    assert out["entry_signal"]["entry_delay_sec"] == 6
    assert ("15", signal_close - 1) in market.calls  # сигнал — на свечах, закрытых к моменту входа
    assert out["verdict"] == "match", out
    assert out["exit"]["live_reason"] == out["exit"]["replay_reason"] == "SL_HIT"


@pytest.mark.asyncio
async def test_use_case_entry_without_signal_is_mismatch():
    s15 = _load("st_sol_15m.csv")
    entry_ms = s15[-1]["timestamp"] + 6_000  # на свеча раньше — разворота ещё не было
    p0 = s15[-2]["close"]
    minutes = [{"timestamp": entry_ms - entry_ms % M, "open": p0, "high": p0, "low": p0, "close": p0, "volume": 1}]
    cfg = {**short_cfg(), "entry_signal": {"type": "supertrend", "timeframe": "15", "st_period": 10,
                                           "st_mult": 3.0, "trend_ema_period": 200, "trend_ema_fast": 50,
                                           "trend_timeframe": "240"}}
    bot = SimpleNamespace(id=2, symbol="SOLUSDT", side="SHORT", exchange="paper", config=cfg)
    position = SimpleNamespace(id=3, opened_at=_dt(entry_ms), is_bot_managed=True, trailing_enabled=True,
                               current_sl=p0 * 1.02)
    orders = [SimpleNamespace(order_number=1, price=p0, status="FILLED", filled_at=_dt(entry_ms), created_at=None)]
    out = await ReconcilePositionUseCase(FakeMarket(minutes)).execute(bot=bot, position=position, orders=orders)
    assert out["verdict"] == "mismatch" and "без сигнала" in out["issues"][0]


# ── bots-health: тики цены у ботов в позиции ─────────────────────────────────

def _health(**kw):
    base = dict(state="PYRAMIDING", config={}, has_open_position=True, registered_for_prices=True,
                scheduler_running=True, scheduler_started_ms=0, last_check=None, now_ms=10 * 60 * M)
    return assess_bot(**{**base, **kw})


def test_health_fresh_tick_ok():
    h = _health(last_tick_ms=10 * 60 * M - 4_000)
    assert h["status"] == "ok" and "4 с назад" in h["notes"][0]


def test_health_stale_tick_problem():
    h = _health(last_tick_ms=10 * 60 * M - 7 * M)
    assert h["status"] == "problem" and "7 мин назад" in h["issues"][0]


def test_health_no_tick_after_restart_is_note():
    h = _health(last_tick_ms=None, scheduler_started_ms=10 * 60 * M - M)
    assert h["status"] == "ok"


def test_health_no_tick_long_after_start_problem():
    h = _health(last_tick_ms=None)
    assert h["status"] == "problem"


@pytest.mark.asyncio
async def test_use_case_straddle_unsupported():
    bot = SimpleNamespace(id=7, symbol="BTCUSDT", side="NEUTRAL", exchange="paper", config={"bot_type": "straddle"})
    out = await ReconcilePositionUseCase(FakeMarket([])).execute(
        bot=bot, position=SimpleNamespace(id=1), orders=[])
    assert out["verdict"] == "unsupported"
