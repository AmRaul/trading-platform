"""Биржа не отдала свечи (адаптер вернул []) → результат data_missing, и планировщик
повторяет проверку той же свечи на следующем тике, а не ждёт следующего закрытия.
Для Supertrend это важно: вход — разворот ровно на последней свече, пропуск = пропущенная сделка."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.signals.check_entry_signal import CheckEntrySignalUseCase
from app.domain.signals.entry_signal import EntrySignalResult
from app.services import signal_scheduler as sched_mod
from app.services.signal_scheduler import SignalEntryScheduler

ST = {"type": "supertrend", "timeframe": "15", "trend_ema_period": 200, "trend_timeframe": "240"}
DON = {"type": "donchian", "timeframe": "60"}


@pytest.mark.asyncio
@pytest.mark.parametrize("cfg,empty_tf", [(ST, "15"), (ST, "240"), (DON, "60"), (DON, "D")])
async def test_empty_fetch_is_data_missing(cfg, empty_tf):
    candle = {"timestamp": 0, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
    md = MagicMock()
    md.get_klines = AsyncMock(side_effect=lambda s, tf, n: [] if tf == empty_tf else [candle])
    uc = CheckEntrySignalUseCase(md)
    r = await uc.execute("SOLUSDT", "SHORT", cfg, 10**12)
    assert r.data_missing and not r.triggered
    if cfg is DON:
        assert (await uc.execute_exit("SOLUSDT", "LONG", cfg, 10**12)).data_missing


class _Session:
    def __init__(self, bots):
        self.bots = bots

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, _q):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.bots))


@pytest.mark.asyncio
async def test_scheduler_retries_same_candle_after_missing_data(monkeypatch):
    bot = SimpleNamespace(id=2, symbol="SOLUSDT", side="SHORT", state="SIGNAL", config={"entry_signal": ST})
    monkeypatch.setattr(sched_mod, "AsyncSessionLocal", lambda: _Session([bot]))
    s = SignalEntryScheduler.__new__(SignalEntryScheduler)
    s._last_checked, s.last_result = {}, {}
    s._check = MagicMock()
    s._check.execute = AsyncMock(side_effect=[
        EntrySignalResult(False, reason="нет данных", data_missing=True),
        EntrySignalResult(False, reason="supertrend=1, разворота нет"),
    ])
    now = 1_000 * 900_000 + 5_000
    await s.run_once(now)
    await s.run_once(now + 60_000)       # та же 15m свеча — проверяется повторно
    await s.run_once(now + 120_000)      # уже проверена успешно — пропуск
    assert s._check.execute.await_count == 2
    assert s.last_result[2]["reason"] == "supertrend=1, разворота нет"
