"""
Честный /health: жив ли бэкенд как торговая система, а не только HTTP-процесс.
Его ждёт CI после деплоя и опрашивает alerter — 503 значит «боты не работают как должны».

  db         — SELECT 1 в Postgres;
  redis      — PING (через Redis идут цены от price-tracker);
  scheduler  — планировщик сигналов запущен (иначе SIGNAL-боты не войдут);
  prices     — слушатель цен жив, если есть на что подписываться (иначе боты в позиции
               не видят стоп/добор). Нет открытых позиций — слушателя нет, это норма.
"""
import asyncio
from typing import Awaitable, Callable, Dict, Tuple

CHECK_TIMEOUT_SEC = 3.0


async def _probe(check: Callable[[], Awaitable[object]]) -> bool:
    try:
        await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SEC)
        return True
    except Exception:
        return False


async def system_health(
    *,
    db_check: Callable[[], Awaitable[object]],
    redis_check: Callable[[], Awaitable[object]],
    scheduler_running: bool,
    price_listener_alive: bool,
) -> Tuple[bool, Dict[str, bool]]:
    db_ok, redis_ok = await asyncio.gather(_probe(db_check), _probe(redis_check))
    checks = {"db": db_ok, "redis": redis_ok, "scheduler": scheduler_running, "prices": price_listener_alive}
    return all(checks.values()), checks
