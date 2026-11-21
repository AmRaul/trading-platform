"""Поправка часов для подписанных запросов Bybit (ErrCode 10002 при спешащих часах сервера)."""
import time

from app.adapters import bybit_clock


def test_measure_offset_when_server_clock_runs_fast(monkeypatch):
    # часы сервера спешат на 4 с: Bybit показывает время на 4000 мс меньше локального
    monkeypatch.setattr(bybit_clock.time, "time", lambda: 1_000_004.0)
    offset = bybit_clock.measure(lambda: {"result": {"timeNano": str(1_000_000_000 * 10**6)}})
    assert offset == -4000


def test_sync_applies_offset_and_timestamp_lands_inside_bybit_window(monkeypatch):
    monkeypatch.setattr(bybit_clock.time, "time", lambda: 1_000_004.0)
    bybit_clock.sync(lambda: {"result": {"timeNano": str(1_000_000_000 * 10**6)}})
    server_ms = 1_000_000_000
    ts = bybit_clock.now_ms()
    # Bybit принимает: не больше 1 с вперёд и не больше recv_window (5 с) назад
    assert -5000 <= ts - server_ms < 1000
    bybit_clock.offset_ms = 0


def test_failed_measure_keeps_previous_offset():
    bybit_clock.offset_ms = -1234

    def boom():
        raise OSError("no network")

    assert bybit_clock.sync(boom) is None and bybit_clock.offset_ms == -1234
    bybit_clock.offset_ms = 0


def test_install_replaces_pybit_timestamp(monkeypatch):
    import types
    import sys
    fake = types.SimpleNamespace(generate_timestamp=lambda: int(time.time() * 1000))
    monkeypatch.setitem(sys.modules, "pybit._helpers", fake)
    monkeypatch.setattr(sys.modules["pybit"], "_helpers", fake, raising=False)
    bybit_clock.install()
    bybit_clock.install()  # повторно — без вложенных обёрток
    assert fake.generate_timestamp is bybit_clock.now_ms
