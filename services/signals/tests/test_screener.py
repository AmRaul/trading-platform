"""Скринер: метрики волатильности и правила сигналов MOMENTUM / REVERSAL / BREAKOUT."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.application.screener.log_signals import _matches_custom
from app.application.screener.update_signal_prices import UpdateSignalPricesUseCase
from app.domain.screener.entities import ScreenerCandidate
from app.domain.screener.signal_detector import SignalDetector
from app.domain.screener.volatility_analyzer import VolatilityAnalyzer
from app.domain.shared.pnl import calc_pnl


def cand(range_pct=50.0, change=0.0, avg=1.0, price=100.0):
    return ScreenerCandidate(symbol="XUSDT", avg_candle_size_pct=avg, atr=1.0, volume_24h=1e6, volume_7d_avg=0,
                             volume_ratio=0, volume_1h=2e5, funding_rate=0.0001, price_change_24h_pct=change,
                             high_24h=110, low_24h=90, open_interest=5e6, direction="FLAT",
                             price_range_pct=range_pct, last_price=price, scanned_at=datetime(2026, 11, 19))


def kinds(signals):
    return sorted((s.strategy, s.side) for s in signals)


@pytest.mark.parametrize("range_pct,change,expected", [
    (90, 20, [("MOMENTUM", "LONG"), ("REVERSAL", "SHORT")]),   # у хая после роста: и импульс, и разворот
    (10, -25, [("MOMENTUM", "SHORT"), ("REVERSAL", "LONG")]),
    (20, -12, [("REVERSAL", "LONG")]),                         # падение не дотянуло до MOMENTUM SHORT
    (50, 2, [("BREAKOUT", "LONG")]),                           # флэт посередине диапазона
    (50, 8, []),                                               # ни тренда, ни флэта
])
def test_detector_rules(range_pct, change, expected):
    assert kinds(SignalDetector().detect_all(cand(range_pct, change), vol_1h_pct=20)) == expected


@pytest.mark.parametrize("kw,vol", [
    (dict(avg=0.2), 20),            # мёртвый рынок
    (dict(), 10),                   # объём часа ниже порога
    (dict(range_pct=None), 20),     # нет дневного диапазона
])
def test_detector_filters(kw, vol):
    assert SignalDetector().detect_all(cand(**{"range_pct": 90, "change": 20, **kw}), vol_1h_pct=vol) == []


def test_signal_carries_entry_and_rounded_volume():
    s = SignalDetector().detect_all(cand(90, 20, price=123.4), vol_1h_pct=20.456)[0]
    assert s.entry_price == 123.4 and s.vol_1h_pct == 20.46


def candles(n, low=100.0, high=101.0):
    return [{"open": low, "high": high, "low": low, "close": (low + high) / 2, "volume": 1} for _ in range(n)]


TICKER = {"turnover24h": "5000000", "lastPrice": "105", "price24hPcnt": "-0.03",
          "highPrice24h": "110", "lowPrice24h": "100", "openInterestValue": "7e6"}


def test_analyzer_metrics():
    c = VolatilityAnalyzer().analyze("XUSDT", candles(35), TICKER, 0.0002,
                                     candles_1h=[{"volume": 1}, {"volume": 250000}])
    assert c.avg_candle_size_pct == 1.0 and c.atr == 1.0
    assert c.price_range_pct == 50.0 and c.price_change_24h_pct == -3.0 and c.direction == "SHORT"
    assert c.volume_1h == 250000 and c.volume_24h == 5e6


def test_analyzer_rejects_quiet_or_short_history():
    a = VolatilityAnalyzer()
    assert a.analyze("X", candles(35, 100, 100.1), TICKER) is None   # 0.1% < порога 0.5%
    assert a.analyze("X", candles(10), TICKER) is None


def test_analyzer_no_range_when_flat_day():
    c = VolatilityAnalyzer().analyze("X", candles(35), {**TICKER, "highPrice24h": "100", "lowPrice24h": "100"})
    assert c.price_range_pct is None


def test_custom_strategy_filters():
    st = SimpleNamespace(vol_1h_min=10, range_min=40, range_max=60, change_min=-5, change_max=5)
    assert _matches_custom(cand(50, 0), st, 15)
    assert not _matches_custom(cand(50, 0), st, 5)
    assert not _matches_custom(cand(70, 0), st, 15)
    assert not _matches_custom(cand(50, 9), st, 15)


def test_pnl_sides():
    assert calc_pnl("LONG", 100, 103) == 3.0
    assert calc_pnl("SHORT", 100, 103) == -3.0


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self.rows)


class FakeDB:
    def __init__(self, rows):
        self.rows, self.commits = rows, 0

    async def execute(self, _):
        return FakeResult(self.rows)

    async def commit(self):
        self.commits += 1


class FakeMD:
    def __init__(self, price):
        self.price = price

    async def get_ticker(self, symbol):
        return {"lastPrice": str(self.price)}


def row(side="LONG", minutes_ago=20, entry=100.0):
    return SimpleNamespace(side=side, symbol="XUSDT", entry_price=entry, status="PENDING",
                           entry_time=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
                           price_15m=None, pnl_15m=None, price_30m=None, pnl_30m=None,
                           price_60m=None, pnl_60m=None)


@pytest.mark.asyncio
async def test_update_prices_fills_checkpoints_by_elapsed_time():
    r = row(minutes_ago=35)
    await UpdateSignalPricesUseCase(FakeMD(102)).execute(FakeDB([r]))
    assert (r.pnl_15m, r.pnl_30m, r.price_60m, r.status) == (2.0, 2.0, None, "PENDING")
    r.entry_time -= timedelta(minutes=30)
    await UpdateSignalPricesUseCase(FakeMD(101)).execute(FakeDB([r]))
    assert (r.pnl_15m, r.pnl_60m, r.status) == (2.0, 1.0, "FILLED")  # уже записанные точки не переписываются


@pytest.mark.asyncio
async def test_update_prices_stop_closes_all_checkpoints():
    r = row(side="SHORT", minutes_ago=5)
    await UpdateSignalPricesUseCase(FakeMD(104.5)).execute(FakeDB([r]))
    assert r.status == "FILLED" and r.pnl_15m == r.pnl_30m == r.pnl_60m == -4.5
