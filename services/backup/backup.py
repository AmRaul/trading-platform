"""
kandle backup — раз в сутки снимает Postgres и шлёт зашифрованные дампы в Telegram-канал.

Зачем Telegram: второй сервер под бэкапы не нужен, канал хранит файлы бессрочно,
а бот уже есть (alerter). Файлы шифруются ДО отправки (AES-256, ключ BACKUP_PASSPHRASE):
в дампе хеши паролей и зашифрованные API-ключи бирж — в Telegram открытым текстом их не кладём.

Что снимается (BACKUP_TARGETS, «имя=postgresql://...;имя=...»):
  trading  — боты, позиции, сделки, журнал разборов (главное: форвард-тест);
  signals  — сигналы скринера.
Базу бэктестера не снимаем: свечи и прогоны воспроизводимы.

Цепочка: pg_dump -Fc → openssl enc → проверка (расшифровать + pg_restore --list) →
нарезка по 45 МБ (лимит Bot API 50 МБ) → sendDocument. Последние BACKUP_KEEP_LOCAL копий
остаются и на сервере (/backups) — для быстрого отката без скачивания.
Сбой — сообщение в TELEGRAM_CHAT_ID (туда же, куда alerter).

Переменные окружения:
    BACKUP_TARGETS           trading=postgresql://u:p@postgres:5432/trading_db;signals=...
    BACKUP_PASSPHRASE        обязателен; без него бэкап не делается (не шлём открытые данные)
    TELEGRAM_BOT_TOKEN
    TELEGRAM_BACKUP_CHAT_ID  канал для файлов (бот — админ канала); пусто → TELEGRAM_CHAT_ID
    TELEGRAM_CHAT_ID         куда писать о сбое
    BACKUP_HOUR_UTC=3  BACKUP_KEEP_LOCAL=7  BACKUP_DIR=/backups

Ручной запуск на сервере:  docker exec trading_backup python backup.py now
Восстановление — services/backup/README.md.
"""
import asyncio
import hashlib
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] backup: %(message)s")
log = logging.getLogger("backup")
logging.getLogger("httpx").setLevel(logging.WARNING)  # в URL Telegram — токен бота

PART_BYTES = 45 * 1024 * 1024
OPENSSL = ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-salt", "-pass", "env:BACKUP_PASSPHRASE"]


def parse_targets(raw: str) -> Dict[str, str]:
    """«trading=postgresql://...;signals=postgresql://...» → {имя: url}. Драйвер (+asyncpg) срезаем."""
    out: Dict[str, str] = {}
    for item in filter(None, (s.strip() for s in raw.split(";"))):
        name, _, url = item.partition("=")
        if not name or not url:
            raise ValueError("BACKUP_TARGETS: каждый элемент — имя=url через «;»")  # сам элемент не печатаем: в нём пароль
        scheme, sep, rest = url.partition("://")
        out[name.strip()] = f"{scheme.split('+')[0]}{sep}{rest}"
    return out


def seconds_until(now: datetime, hour_utc: int) -> float:
    """Секунд до ближайшего hour_utc:00 UTC (строго в будущем)."""
    nxt = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()


def split_file(path: Path, part_bytes: Optional[int] = None) -> List[Path]:
    """Режет файл на куски для Bot API. Один кусок — сам файл. Склейка: cat file.part* > file."""
    part_bytes = part_bytes or PART_BYTES
    size = path.stat().st_size
    if size <= part_bytes:
        return [path]
    parts = []
    with path.open("rb") as src:
        i = 1
        while chunk := src.read(part_bytes):
            p = path.with_name(f"{path.name}.part{i:02d}")
            p.write_bytes(chunk)
            parts.append(p)
            i += 1
    return parts


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def human(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def dump_encrypted(url: str, out: Path, passphrase: str) -> None:
    """pg_dump -Fc | openssl enc > out, затем проверка: файл расшифровывается и читается pg_restore."""
    env = {**os.environ, "BACKUP_PASSPHRASE": passphrase}
    tmp = out.with_suffix(out.suffix + ".tmp")
    with tmp.open("wb") as fh:
        dump = subprocess.Popen(["pg_dump", "-Fc", "--no-owner", "--no-privileges", "-d", url],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        enc = subprocess.Popen(OPENSSL, stdin=dump.stdout, stdout=fh, stderr=subprocess.PIPE, env=env)
        dump.stdout.close()
        enc_err = enc.communicate()[1]
        dump_err = dump.stderr.read()
        dump.wait()
    if dump.returncode != 0:
        tmp.unlink(missing_ok=True)
        # в stderr pg_dump бывает URL с паролем — наружу только первая строка без него
        raise RuntimeError(f"pg_dump: {_scrub(dump_err.decode(errors='replace'), url)}")
    if enc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"openssl: {enc_err.decode(errors='replace').strip()[:300]}")
    verify(tmp, passphrase)
    tmp.rename(out)


def verify(path: Path, passphrase: str) -> int:
    """Расшифровать и прочитать оглавление дампа. Возвращает число объектов."""
    env = {**os.environ, "BACKUP_PASSPHRASE": passphrase}
    with path.open("rb") as fh:
        dec = subprocess.Popen(OPENSSL + ["-d"], stdin=fh, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        lst = subprocess.run(["pg_restore", "-l"], stdin=dec.stdout, capture_output=True)
        dec.stdout.close()
        dec.wait()
    if dec.returncode != 0 or lst.returncode != 0:
        raise RuntimeError("проверка не прошла: дамп не расшифровывается или не читается pg_restore")
    return sum(1 for line in lst.stdout.decode().splitlines() if line and not line.startswith(";"))


def _scrub(text: str, url: str) -> str:
    line = (text.strip().splitlines() or [""])[0]
    pw = url.split("://", 1)[-1].split("@", 1)[0].partition(":")[2]
    return (line.replace(pw, "***") if pw else line)[:300]


def prune(directory: Path, name: str, keep: int) -> None:
    files = sorted(directory.glob(f"{name}_*.dump.enc"))
    for old in files[:-keep] if keep > 0 else files:
        old.unlink()


class Telegram:
    def __init__(self, token: str, files_chat: str, alert_chat: str):
        self.token, self.files_chat, self.alert_chat = token, files_chat, alert_chat
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=15.0))

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.files_chat)

    async def _call(self, method: str, **kw) -> None:
        last = ""
        for attempt in range(3):
            try:
                r = await self.http.post(f"https://api.telegram.org/bot{self.token}/{method}", **kw)
                if r.status_code == 200:
                    return
                last = f"HTTP {r.status_code}: {r.text[:200]}"
            except httpx.HTTPError as e:
                last = type(e).__name__
            await asyncio.sleep(5 * (attempt + 1))
        raise RuntimeError(f"Telegram {method}: {last}")

    async def send_file(self, path: Path, caption: str) -> None:
        with path.open("rb") as fh:
            await self._call("sendDocument", data={"chat_id": self.files_chat, "caption": caption},
                             files={"document": (path.name, fh, "application/octet-stream")})

    async def alert(self, text: str) -> None:
        if not (self.token and self.alert_chat):
            log.error(f"[нет TELEGRAM_*] {text}")
            return
        try:
            await self._call("sendMessage", json={"chat_id": self.alert_chat, "text": text})
        except RuntimeError as e:
            log.error(f"не смог отправить алерт: {e}")


@dataclass
class Config:
    targets: Dict[str, str]
    passphrase: str
    directory: Path
    keep_local: int = 7
    hour_utc: int = 3

    @classmethod
    def from_env(cls, env=os.environ) -> "Config":
        return cls(targets=parse_targets(env.get("BACKUP_TARGETS", "")),
                   passphrase=env.get("BACKUP_PASSPHRASE", ""),
                   directory=Path(env.get("BACKUP_DIR", "/backups")),
                   keep_local=int(env.get("BACKUP_KEEP_LOCAL", "7")),
                   hour_utc=int(env.get("BACKUP_HOUR_UTC", "3")))


async def backup_once(cfg: Config, tg: Telegram, now: Optional[datetime] = None) -> List[str]:
    """Снять все базы, отправить. Возвращает список ошибок (пусто — всё хорошо)."""
    if not cfg.passphrase:
        msg = "🔴 kandle: бэкап не сделан — не задан BACKUP_PASSPHRASE (без шифрования в Telegram не шлём)"
        await tg.alert(msg)
        return [msg]
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d_%H%M")
    cfg.directory.mkdir(parents=True, exist_ok=True)
    errors: List[str] = []
    for name, url in cfg.targets.items():
        out = cfg.directory / f"{name}_{stamp}.dump.enc"
        started = time.monotonic()
        parts: List[Path] = []
        try:
            dump_encrypted(url, out, cfg.passphrase)
            size, digest = out.stat().st_size, sha256(out)
            parts = split_file(out)
            if tg.enabled:
                for i, part in enumerate(parts, 1):
                    piece = f" · часть {i}/{len(parts)}" if len(parts) > 1 else ""
                    await tg.send_file(part, f"💾 {name} {stamp} UTC · {human(size)}{piece}\nsha256 {digest[:16]}")
            else:
                log.warning("TELEGRAM_* не заданы — копия только на сервере")
            log.info(f"{name}: {human(size)} за {time.monotonic() - started:.0f} с, частей {len(parts)}")
        except Exception as e:
            errors.append(f"{name}: {e}")
            log.error(f"{name}: {e}")
        finally:
            for p in parts:
                if p != out:
                    p.unlink(missing_ok=True)
        prune(cfg.directory, name, cfg.keep_local)
    if errors:
        await tg.alert("🔴 kandle: бэкап не удался\n" + "\n".join(f"• {e}" for e in errors))
    return errors


async def main(argv: List[str]) -> int:
    env = os.environ
    cfg = Config.from_env(env)
    tg = Telegram(env.get("TELEGRAM_BOT_TOKEN", ""),
                  env.get("TELEGRAM_BACKUP_CHAT_ID") or env.get("TELEGRAM_CHAT_ID", ""),
                  env.get("TELEGRAM_CHAT_ID", ""))
    if not cfg.targets:
        log.error("BACKUP_TARGETS пуст — нечего снимать")
        return 2
    if argv[1:2] == ["now"]:
        return 1 if await backup_once(cfg, tg) else 0
    log.info(f"бэкап {', '.join(cfg.targets)} ежедневно в {cfg.hour_utc:02d}:00 UTC, локально хранится {cfg.keep_local}")
    while True:
        await asyncio.sleep(seconds_until(datetime.now(timezone.utc), cfg.hour_utc))
        try:
            await backup_once(cfg, tg)
        except Exception as e:  # сервис не должен умирать из-за одного сбоя
            log.error(f"бэкап упал: {e}", exc_info=True)
            await tg.alert(f"🔴 kandle: бэкап упал: {type(e).__name__}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv)))
