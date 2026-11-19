"""
kandle alerter — пишет в Telegram, когда торговая система перестаёт работать как должна.

Раз в INTERVAL_SEC:
  1. GET /health бэкенда — db, redis, планировщик сигналов, поток цен (503 = что-то не так);
  2. GET /api/analytics/bots-health — проблемы по ботам (тики встали, сигнал не проверяется, выпал в IDLE).
Сообщение — когда проблема появилась, когда ушла, и напоминание, если держится REMIND_HOURS.
Недоступность бэкенда — только после DOWN_AFTER проверок подряд (рестарт при деплое — не тревога).

Отдельный контейнер, а не часть бэкенда: иначе он падал бы вместе с тем, за кем следит.

Переменные окружения:
    KANDLE_URL           — http://backend:8000
    KANDLE_USERNAME      — логин kandle, чьих ботов проверять
    KANDLE_PASSWORD
    TELEGRAM_BOT_TOKEN   — от @BotFather; без него — только лог (сухой режим)
    TELEGRAM_CHAT_ID
    INTERVAL_SEC=300  DOWN_AFTER=2  REMIND_HOURS=6
"""
import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] alerter: %(message)s")
log = logging.getLogger("alerter")
# httpx пишет каждый запрос с полным URL, а в URL Telegram — токен бота: в логи (Loki) его не пускаем
logging.getLogger("httpx").setLevel(logging.WARNING)

HEALTH_NAMES = {"db": "база данных", "redis": "Redis (цены)", "scheduler": "планировщик сигналов",
                "prices": "поток цен"}


def problem_key(scope: str, text: str) -> str:
    """Ключ без чисел: «тик 7 мин назад» и «тик 12 мин назад» — одна и та же проблема."""
    return f"{scope}:{re.sub(r'[0-9.,]+', '#', text)}"


def collect_problems(health_status: Optional[int], health_body: Optional[Dict],
                     bots_health: Optional[Dict]) -> Dict[str, str]:
    """{ключ: текст} текущих проблем. health_status None — бэкенд не ответил."""
    out: Dict[str, str] = {}
    if health_status is None:
        out["backend:down"] = "бэкенд не отвечает"
        return out
    if health_status != 200:
        checks = (health_body or {}).get("checks") or {}
        bad = [HEALTH_NAMES.get(k, k) for k, ok in checks.items() if not ok]
        text = "не работает: " + ", ".join(bad) if bad else f"/health ответил {health_status}"
        out[problem_key("health", text)] = text
    for b in (bots_health or {}).get("bots", []):
        if b.get("status") != "problem":
            continue
        for issue in b.get("issues", []):
            text = f"бот {b['bot_id']} {b.get('symbol', '')}: {issue}"
            out[problem_key(f"bot:{b['bot_id']}", issue)] = text
    return out


@dataclass
class AlertState:
    down_after: int = 2
    remind_sec: float = 6 * 3600
    active: Dict[str, Tuple[str, float, float]] = field(default_factory=dict)  # key -> (text, since, last_sent)
    down_streak: int = 0

    def update(self, problems: Dict[str, str], now: float) -> List[str]:
        """Сообщения для отправки по итогам одной проверки."""
        backend_down = "backend:down" in problems
        if backend_down:
            self.down_streak += 1
            if self.down_streak < self.down_after:
                return []  # ждём подтверждения: короткий рестарт при деплое — не тревога
            problems = {"backend:down": f"бэкенд не отвечает {self.down_streak} проверки подряд"}
        else:
            self.down_streak = 0

        new = [(k, t) for k, t in problems.items() if k not in self.active]
        # Пока бэкенд лежит, про ботов ничего не известно — их проблемы не «восстановились»
        gone = [(k, self.active[k][0]) for k in list(self.active)
                if k not in problems and not (backend_down and k != "backend:down")]
        remind = [(k, problems[k], since) for k, (_, since, sent) in self.active.items()
                  if k in problems and now - sent >= self.remind_sec]

        msgs: List[str] = []
        if new:
            msgs.append("🔴 kandle: проблема\n" + "\n".join(f"• {t}" for _, t in new))
        if gone:
            msgs.append("✅ kandle: восстановилось\n" + "\n".join(f"• {t}" for _, t in gone))
        if remind:
            msgs.append("⏰ kandle: всё ещё не так\n" + "\n".join(
                f"• {t} (уже {int((now - since) // 3600)} ч)" for _, t, since in remind))

        for k, t in new:
            self.active[k] = (t, now, now)
        for k, _ in gone:
            del self.active[k]
        for k, t, since in remind:
            self.active[k] = (t, since, now)
        return msgs


class Kandle:
    def __init__(self, base: str, username: str, password: str):
        self.http = httpx.AsyncClient(base_url=base.rstrip("/"), timeout=15.0)
        self.username, self.password = username, password
        self.token: Optional[str] = None

    async def health(self) -> Tuple[Optional[int], Optional[Dict]]:
        try:
            r = await self.http.get("/health")
        except httpx.HTTPError:
            return None, None
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, None

    async def _login(self):
        r = await self.http.post("/api/auth/login", json={"username": self.username, "password": self.password})
        r.raise_for_status()
        self.token = r.json()["access_token"]

    async def bots_health(self) -> Optional[Dict]:
        try:
            if not self.token:
                await self._login()
            for attempt in (1, 2):
                r = await self.http.get("/api/analytics/bots-health", headers={"Authorization": f"Bearer {self.token}"})
                if r.status_code == 401 and attempt == 1:
                    await self._login()
                    continue
                r.raise_for_status()
                return r.json()
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning(f"bots-health недоступен: {e}")
        return None


class Telegram:
    def __init__(self, token: str, chat_id: str):
        self.token, self.chat_id = token, chat_id
        self.http = httpx.AsyncClient(timeout=15.0)

    async def send(self, text: str):
        if not self.token or not self.chat_id:
            log.info(f"[dry-run, нет TELEGRAM_*] {text}")
            return
        try:
            r = await self.http.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                                     json={"chat_id": self.chat_id, "text": text})
            if r.status_code != 200:
                log.error(f"Telegram ответил {r.status_code}: {r.text[:200]}")
        except httpx.HTTPError as e:
            log.error(f"Telegram недоступен: {e}")


async def check_once(kandle: Kandle, state: AlertState, tg: Telegram, now: Optional[float] = None) -> Dict[str, str]:
    status, body = await kandle.health()
    bots = await kandle.bots_health() if status is not None else None
    problems = collect_problems(status, body, bots)
    for msg in state.update(problems, now or time.time()):
        log.info(msg.replace("\n", " | "))
        await tg.send(msg)
    return problems


async def main():
    env = os.environ
    kandle = Kandle(env.get("KANDLE_URL", "http://backend:8000"), env.get("KANDLE_USERNAME", ""),
                    env.get("KANDLE_PASSWORD", ""))
    tg = Telegram(env.get("TELEGRAM_BOT_TOKEN", ""), env.get("TELEGRAM_CHAT_ID", ""))
    interval = float(env.get("INTERVAL_SEC", "300"))
    state = AlertState(down_after=int(env.get("DOWN_AFTER", "2")),
                       remind_sec=float(env.get("REMIND_HOURS", "6")) * 3600)

    await asyncio.sleep(float(env.get("START_DELAY_SEC", "60")))  # дать бэкенду подняться после деплоя
    bots = await kandle.bots_health()
    n = len(bots["bots"]) if bots else "?"
    await tg.send(f"🟢 kandle alerter запущен: слежу за ботами ({n}) и /health каждые {int(interval // 60)} мин")
    while True:
        try:
            await check_once(kandle, state, tg)
        except Exception as e:  # алертер не должен падать из-за одной кривой проверки
            log.error(f"проверка упала: {e}", exc_info=True)
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(main())
