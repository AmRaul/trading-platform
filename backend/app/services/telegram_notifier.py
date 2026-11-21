"""Уведомления о сделках в Telegram: вход, добор, выход, конец straddle.

Подключено к публикации событий движка (adapters/websocket_publisher.py): то же событие,
что уходит в браузер, уходит и сюда. Отправка — отдельной задачей и с таймаутом,
торговый цикл её никогда не ждёт; сбой Telegram только пишется в лог.

Каждому — в его личный чат: пользователь привязывает Telegram в «Настройках» (код /start
боту, services/telegram_bot.py). Проблемы по ботам (бот встал, биржа не подтвердила ордер,
позиция без бота) — services/user_alerts.py пользователям, services/alerter — владельцу.

Настройки: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (чат владельца, пока он не привязал свой),
TELEGRAM_NOTIFY = all | real | off (глобально), у пользователя — users.telegram_notify.
"""
import asyncio
import logging
import time
from typing import Dict, Optional, Set, Tuple

import aiohttp

from app.core.config import settings

logger = logging.getLogger(__name__)

EVENTS = {"position_opened", "pyramiding_order_added", "position_closed", "straddle_finished"}

EXIT_REASONS = {
    "TP_HIT": "тейк", "SL_HIT": "стоп", "TRAILING_STOP": "трейлинг", "MANUAL_CLOSE": "вручную",
    "EXCHANGE_CLOSED": "закрыта на бирже", "TIME_STOP": "стоп по времени", "MAX_REARMS": "лимит пил",
}


def _num(x: Optional[float]) -> str:
    """Цена без лишних нулей, но с точностью для дешёвых монет."""
    if x is None:
        return "—"
    x = float(x)
    if x == 0:
        return "0"
    digits = 2 if abs(x) >= 100 else 4 if abs(x) >= 1 else 6
    return f"{x:,.{digits}f}".replace(",", " ").rstrip("0").rstrip(".")


def _usd(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:+.2f}$"


def format_event(event: str, d: Dict, name: str, exchange: str, order_count: Optional[int]) -> Optional[str]:
    tag = "📝 " if exchange == "paper" else ""
    side, symbol = d.get("side", ""), d.get("symbol", "")
    if event == "position_opened":
        return (f"{tag}🟢 Вход · {name}\n{side} {symbol} @ {_num(d.get('price'))} · {d.get('size', 0):.0f}$"
                f" · стоп {_num(d.get('sl'))}")
    if event == "pyramiding_order_added":
        of = f"/{order_count}" if order_count else ""
        return (f"{tag}➕ Ордер #{d.get('order_number')}{of} · {name}\n{side} {symbol} @ {_num(d.get('price'))}"
                f" · средняя {_num(d.get('new_average_price'))} · стоп {_num(d.get('new_sl'))}"
                f" · сейчас {_usd(d.get('unrealized_pnl'))}")
    if event == "position_closed":
        pnl = d.get("pnl") or 0.0
        icon = "✅" if pnl > 0 else "🔴"
        raw = (d.get("exit_reason") or "").removeprefix("STRADDLE_")
        reason = EXIT_REASONS.get(raw, raw)
        pct = d.get("pnl_percent")
        orders = f" · ордеров {d.get('total_orders')}" if d.get("total_orders") else ""
        return (f"{tag}{icon} Выход ({reason}) · {name}\n{side} {symbol} @ {_num(d.get('exit_price'))}"
                f" · {_usd(pnl)}" + (f" ({pct:+.2f}%)" if pct is not None else "") + orders)
    if event == "straddle_finished":
        reason = EXIT_REASONS.get(d.get("reason") or "", d.get("reason") or "")
        return (f"{tag}🏁 Straddle завершён ({reason}) · {name}\n{symbol} · итог {_usd(d.get('realized'))}"
                f" · пил {d.get('rearms', 0)}")
    return None


ROUTE_TTL_SEC = 60  # настройки Telegram пользователя перечитываются не реже раза в минуту


class TelegramNotifier:
    """Каждое событие — в личный чат владельца бота (users.telegram_chat_id) с его режимом
    (users.telegram_notify: all | real | off). У владельца платформы (ADMIN_USERNAME), пока
    он не привязал чат сам, — чат из TELEGRAM_CHAT_ID, как раньше. Пользователь без
    привязанного чата, заблокированный или не одобренный — ничего не получает.
    TELEGRAM_NOTIFY=off выключает всё, real — бумажных не шлёт никому."""

    def __init__(self, token: str = "", owner_chat_id: str = "", mode: str = "all", owner: str = ""):
        self.token, self.owner_chat_id = token, owner_chat_id
        self.mode = (mode or "all").lower()
        self.owner = owner
        self._bots: Dict[int, Tuple[str, str, Optional[int], Optional[int]]] = {}  # bot_id -> (имя, площадка, сетка, user_id)
        self._routes: Dict[int, Tuple[float, Optional[Tuple[str, str]]]] = {}  # user_id -> (когда прочитан, (чат, режим))
        self._tasks: Set[asyncio.Task] = set()

    @property
    def enabled(self) -> bool:
        return bool(self.token) and self.mode != "off"

    def route_for(self, user) -> Optional[Tuple[str, str]]:
        """(чат, режим) пользователя или None — ему не шлём."""
        if user is None:
            return None
        is_owner = bool(self.owner) and user.username == self.owner
        if not is_owner and (user.is_active is False or not user.approved):
            return None
        chat = user.telegram_chat_id or (self.owner_chat_id if is_owner else None)
        mode = (user.telegram_notify or "all").lower()
        if not chat or mode == "off":
            return None
        if self.mode == "real":
            mode = "real"
        return chat, mode

    async def _bot_info(self, bot_id: int) -> Tuple[str, str, Optional[int], Optional[int]]:
        if bot_id not in self._bots:
            from sqlalchemy import select
            from app.core.database import AsyncSessionLocal
            from app.models import Bot
            async with AsyncSessionLocal() as db:
                bot = (await db.execute(select(Bot).where(Bot.id == bot_id))).scalar_one_or_none()
            if bot is None:
                return f"бот {bot_id}", "", None, None
            self._bots[bot_id] = (bot.name, bot.exchange, (bot.config or {}).get("order_count"), bot.user_id)
        return self._bots[bot_id]

    async def _route(self, user_id: Optional[int]) -> Optional[Tuple[str, str]]:
        if user_id is None:
            return None
        cached = self._routes.get(user_id)
        if cached and time.monotonic() - cached[0] < ROUTE_TTL_SEC:
            return cached[1]
        from app.core.database import AsyncSessionLocal
        from app.models import User
        async with AsyncSessionLocal() as db:
            route = self.route_for(await db.get(User, user_id))
        self._routes[user_id] = (time.monotonic(), route)
        return route

    def forget(self, bot_id: int) -> None:
        """Бота переименовали/удалили — перечитать при следующем событии."""
        self._bots.pop(bot_id, None)

    def forget_user(self, user_id: int) -> None:
        """Пользователь сменил настройки Telegram / его одобрили или заблокировали."""
        self._routes.pop(user_id, None)

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def notify(self, event: str, data: Dict) -> None:
        """Не ждёт отправки: вызывается из торгового цикла."""
        if not self.enabled or event not in EVENTS or "bot_id" not in data:
            return
        self._spawn(self._send_event(event, dict(data)))

    def notify_owner(self, text: str) -> None:
        """Служебное владельцу платформы (новая заявка на регистрацию)."""
        if self.enabled:
            self._spawn(self._send_owner(text))

    async def _send_owner(self, text: str) -> None:
        try:
            from sqlalchemy import select
            from app.core.database import AsyncSessionLocal
            from app.models import User
            async with AsyncSessionLocal() as db:
                owner = (await db.execute(select(User).where(User.username == self.owner))).scalar_one_or_none()
            chat = (owner.telegram_chat_id if owner else None) or self.owner_chat_id
            if chat:
                await self.send(text, chat)
        except Exception as e:
            logger.warning(f"[Telegram] owner message: {e}")

    async def _send_event(self, event: str, data: Dict) -> None:
        try:
            name, exchange, order_count, user_id = await self._bot_info(data["bot_id"])
            route = await self._route(user_id)
            if not route:
                return
            chat, mode = route
            if mode == "real" and exchange == "paper":
                return
            text = format_event(event, data, name, exchange, order_count)
            if text:
                await self.send(text, chat)
        except Exception as e:
            logger.warning(f"[Telegram] {event} bot={data.get('bot_id')}: {e}")

    async def send(self, text: str, chat_id: str) -> bool:
        return await telegram_call(self.token, "sendMessage",
                                   {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}) is not None


async def telegram_call(token: str, method: str, payload: Dict, timeout: float = 10) -> Optional[Dict]:
    """Вызов Bot API с повтором при сбое сети и 429. Возвращает result или None.
    В лог не пишет URL — в нём токен."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout + 5)) as s:
                async with s.post(url, json=payload) as r:
                    body = await r.json(content_type=None)
                    if r.status == 200 and body.get("ok"):
                        return body.get("result")
                    if r.status == 429:
                        await asyncio.sleep(float(body.get("parameters", {}).get("retry_after", 3)))
                        continue
                    logger.warning(f"[Telegram] {method} {r.status}: {str(body.get('description'))[:200]}")
                    return None
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[Telegram] {method} attempt {attempt + 1}: {type(e).__name__}")
            await asyncio.sleep(2 * (attempt + 1))
    return None


notifier = TelegramNotifier(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID, settings.TELEGRAM_NOTIFY,
                            owner=settings.ADMIN_USERNAME)
