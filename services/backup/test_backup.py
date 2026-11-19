"""Тесты бэкапа без сети и без Postgres: python -m pytest services/backup"""
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

import backup as bk


def test_parse_targets_strips_driver():
    t = bk.parse_targets("trading=postgresql+asyncpg://u:p@postgres:5432/trading_db; signals=postgresql://s:x@signals-db/signals_db;")
    assert t == {"trading": "postgresql://u:p@postgres:5432/trading_db",
                 "signals": "postgresql://s:x@signals-db/signals_db"}


def test_parse_targets_rejects_garbage_without_leaking():
    with pytest.raises(ValueError) as e:
        bk.parse_targets("postgresql://u:secret@h/db")
    assert "secret" not in str(e.value)


@pytest.mark.parametrize("now,hours", [
    (datetime(2026, 11, 19, 1, 30, tzinfo=timezone.utc), 1.5),
    (datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc), 24),     # ровно в срок — следующий через сутки
    (datetime(2026, 11, 19, 22, 0, tzinfo=timezone.utc), 5),
])
def test_seconds_until(now, hours):
    assert bk.seconds_until(now, 3) == hours * 3600


def test_split_small_file_is_itself(tmp_path):
    f = tmp_path / "a.dump.enc"
    f.write_bytes(b"x" * 10)
    assert bk.split_file(f, part_bytes=10) == [f]


def test_split_and_join_back(tmp_path):
    f = tmp_path / "a.dump.enc"
    data = bytes(range(256)) * 10
    f.write_bytes(data)
    parts = bk.split_file(f, part_bytes=1000)
    assert [p.name for p in parts] == ["a.dump.enc.part01", "a.dump.enc.part02", "a.dump.enc.part03"]
    assert b"".join(p.read_bytes() for p in sorted(parts)) == data


def test_prune_keeps_newest(tmp_path):
    for d in ("2026-11-15", "2026-11-16", "2026-11-17", "2026-11-18"):
        (tmp_path / f"trading_{d}_0300.dump.enc").write_bytes(b"x")
    (tmp_path / "signals_2026-11-10_0300.dump.enc").write_bytes(b"x")
    bk.prune(tmp_path, "trading", keep=2)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "signals_2026-11-10_0300.dump.enc", "trading_2026-11-17_0300.dump.enc", "trading_2026-11-18_0300.dump.enc"]


def test_scrub_hides_password():
    url = "postgresql://trading:S3cr3t@postgres:5432/trading_db"
    assert "S3cr3t" not in bk._scrub(f'connection to "{url}" failed\nmore', url)


class FakeTG:
    def __init__(self, enabled=True):
        self.files, self.alerts, self.enabled = [], [], enabled

    async def send_file(self, path, caption):
        self.files.append((path.name, caption, path.read_bytes()))

    async def alert(self, text):
        self.alerts.append(text)


def test_no_passphrase_no_backup(tmp_path):
    tg = FakeTG()
    cfg = bk.Config(targets={"trading": "postgresql://x"}, passphrase="", directory=tmp_path)
    errs = asyncio.run(bk.backup_once(cfg, tg))
    assert errs and tg.alerts and "BACKUP_PASSPHRASE" in tg.alerts[0] and not tg.files
    assert not list(tmp_path.iterdir())


def test_backup_once_sends_parts_and_cleans(tmp_path, monkeypatch):
    def fake_dump(url, out, passphrase):
        out.write_bytes(b"e" * 2500)
    monkeypatch.setattr(bk, "dump_encrypted", fake_dump)
    monkeypatch.setattr(bk, "PART_BYTES", 1000)
    tg = FakeTG()
    cfg = bk.Config(targets={"trading": "postgresql://x"}, passphrase="pw", directory=tmp_path)
    now = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)
    assert asyncio.run(bk.backup_once(cfg, tg, now=now)) == []
    assert [c for _, c, _ in tg.files][0].startswith("💾 trading 2026-11-19_0300 UTC")
    assert "часть 1/3" in tg.files[0][1] and "часть 3/3" in tg.files[2][1]
    assert sum(len(b) for *_, b in tg.files) == 2500
    assert [p.name for p in tmp_path.iterdir()] == ["trading_2026-11-19_0300.dump.enc"]  # куски удалены
    assert not tg.alerts


def test_failure_alerts_and_continues(tmp_path, monkeypatch):
    def fake_dump(url, out, passphrase):
        if "bad" in url:
            raise RuntimeError("pg_dump: connection refused")
        out.write_bytes(b"ok")
    monkeypatch.setattr(bk, "dump_encrypted", fake_dump)
    tg = FakeTG()
    cfg = bk.Config(targets={"signals": "postgresql://bad", "trading": "postgresql://good"},
                    passphrase="pw", directory=tmp_path)
    errs = asyncio.run(bk.backup_once(cfg, tg))
    assert errs == ["signals: pg_dump: connection refused"]
    assert len(tg.files) == 1 and tg.files[0][1].startswith("💾 trading")
    assert len(tg.alerts) == 1 and "signals" in tg.alerts[0]

