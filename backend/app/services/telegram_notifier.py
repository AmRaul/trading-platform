"""Уведомления о сделках в Telegram: вход, добор, выход, конец straddle.

Подключено к публикации событий движка (adapters/websocket_publisher.py): то же событие,
что уходит в браузер, уходит и сюда. Отправка — отдельной задачей и с таймаутом,
торговый цикл её никогда не ждёт; сбой Telegram только пишется в лог.

Проблемы (бот встал, биржа не подтвердила ордер, позиция без бота) шлёт не он,
а services/alerter — по bots-health.

Настройки: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_NOTIFY = all | real | off.
Чат один — владельца платформы, поэтому уведомления только по ботам пользователя
ADMIN_USERNAME: сделки других зарегистрированных пользователей в него не попадают.
Пустой ADMIN_USERNAME — уведомлений нет (не знаем, чей это чат).
"""
import asyncio
import logging
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


class TelegramNotifier:
    def __init__(self, token: str = "", chat_id: str = "", mode: str = "all", owner: str = ""):
        self.token, self.chat_id, self.mode = token, chat_id, (mode or "all").lower()
        self.owner = owner  # логин, чьи боты шлём в чат
        # bot_id -> (имя, площадка, ордеров в сетке, бот владельца чата)
        self._bots: Dict[int, Tuple[str, str, Optional[int], bool]] = {}
        self._tasks: Set[asyncio.Task] = set()

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id and self.owner) and self.mode != "off"

    async def _bot_info(self, bot_id: int) -> Tuple[str, str, Optional[int], bool]:
        if bot_id not in self._bots:
            from sqlalchemy import select
            from app.core.database import AsyncSessionLocal
            from app.models import Bot, User
            async with AsyncSessionLocal() as db:
                row = (await db.execute(select(Bot, User.username).join(User, User.id == Bot.user_id, isouter=True)
                                        .where(Bot.id == bot_id))).first()
            if row is None:
                return f"бот {bot_id}", "", None, False
            bot, username = row
            self._bots[bot_id] = (bot.name, bot.exchange, (bot.config or {}).get("order_count"),
                                  username == self.owner)
        return self._bots[bot_id]

    def forget(self, bot_id: int) -> None:
        """Бота переименовали/удалили — перечитать при следующем событии."""
        self._bots.pop(bot_id, None)

    def notify(self, event: str, data: Dict) -> None:
        """Не ждёт отправки: вызывается из торгового цикла."""
        if not self.enabled or event not in EVENTS or "bot_id" not in data:
            return
        task = asyncio.create_task(self._send_event(event, dict(data)))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _send_event(self, event: str, data: Dict) -> None:
        try:
            name, exchange, order_count, owners = await self._bot_info(data["bot_id"])
            if not owners:
                return  # бот другого пользователя — не в чат владельца платформы
            if self.mode == "real" and exchange == "paper":
                return
            text = format_event(event, data, name, exchange, order_count)
            if text:
                await self.send(text)
        except Exception as e:
            logger.warning(f"[Telegram] {event} bot={data.get('bot_id')}: {e}")

    async def send(self, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        for attempt in range(3):
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                    async with s.post(url, json={"chat_id": self.chat_id, "text": text,
                                                 "disable_web_page_preview": True}) as r:
                        if r.status == 200:
                            return True
                        if r.status == 429:
                            await asyncio.sleep(float((await r.json()).get("parameters", {}).get("retry_after", 3)))
                            continue
                        logger.warning(f"[Telegram] sendMessage {r.status}: {(await r.text())[:200]}")
                        return False
            except Exception as e:
                logger.warning(f"[Telegram] sendMessage attempt {attempt + 1}: {type(e).__name__}")
                await asyncio.sleep(2 * (attempt + 1))
        return False


notifier = TelegramNotifier(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID, settings.TELEGRAM_NOTIFY,
                            owner=settings.ADMIN_USERNAME)
