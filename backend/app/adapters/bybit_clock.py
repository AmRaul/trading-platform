"""Поправка часов для подписанных запросов Bybit.

Bybit отклоняет запрос (ErrCode 10002), если его метка времени опережает часы Bybit
больше чем на 1 с или отстаёт больше чем на recv_window. На VPS часы уходят (у нас
спешили на ~4 с) — и ни проверка ключа, ни подтверждение ордеров Cryptorg не работали.

pybit берёт метку из pybit._helpers.generate_timestamp(). Подменяем её: локальное
время + поправка до часов Bybit (замер по публичному /v5/market/time при старте
и раз в RESYNC_SEC) − небольшой запас, чтобы метка никогда не оказалась «из будущего».
Синхронизация NTP на сервере всё равно полезна — это страховка, а не замена.
"""
import asyncio
import json
import logging
import time
import urllib.request
from typing import Callable, Optional

logger = logging.getLogger(__name__)

TIME_URL = "https://api.bybit.com/v5/market/time"
RESYNC_SEC = 600
# Метка ставится на столько раньше часов Bybit: опережение больше 1 с — отказ,
# отставание до recv_window (5 с у pybit) — норма
SAFETY_MS = 500
WARN_DRIFT_MS = 1000

offset_ms = 0  # часы Bybit − локальные часы
last_sync: Optional[float] = None


def now_ms() -> int:
    return int(time.time() * 1000) + offset_ms - SAFETY_MS


def measure(fetch: Optional[Callable[[], dict]] = None) -> Optional[int]:
    """Поправка в мс по одному замеру (середина запроса против времени Bybit) или None."""
    fetch = fetch or (lambda: json.loads(urllib.request.urlopen(TIME_URL, timeout=5).read()))
    t0 = time.time() * 1000
    try:
        body = fetch()
    except Exception as e:
        logger.warning(f"[BybitClock] нет времени Bybit: {e}")
        return None
    t1 = time.time() * 1000
    result = body.get("result") or {}
    if result.get("timeNano"):
        server = int(result["timeNano"]) / 1e6
    elif body.get("time"):
        server = float(body["time"])
    else:
        return None
    return int(server - (t0 + t1) / 2)


def sync(fetch: Optional[Callable[[], dict]] = None) -> Optional[int]:
    """Замерить и применить поправку. Блокирующий вызов — из потока или при старте."""
    global offset_ms, last_sync
    measured = measure(fetch)
    if measured is None:
        return None
    offset_ms, last_sync = measured, time.time()
    if abs(offset_ms) >= WARN_DRIFT_MS:
        logger.warning(f"[BybitClock] часы сервера расходятся с Bybit на {-offset_ms / 1000:+.1f} с — "
                       f"поправка применена; стоит включить синхронизацию времени (chrony/NTP)")
    return offset_ms


def install() -> None:
    """Подменить генератор метки pybit (один раз; повторный вызов безопасен)."""
    from pybit import _helpers
    if getattr(_helpers.generate_timestamp, "_kandle_clock", False):
        return
    now_ms._kandle_clock = True  # type: ignore[attr-defined]
    _helpers.generate_timestamp = now_ms


async def resync_loop() -> None:
    while True:
        await asyncio.get_running_loop().run_in_executor(None, sync)
        await asyncio.sleep(RESYNC_SEC)
