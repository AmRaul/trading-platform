"""Сторож «на бирже позиция есть, а у бота её нет».

Так бывает, если команда входа исполнилась, а бот об этом не узнал: webhook Cryptorg
ответил ошибкой или по таймауту, но сделку открыл; бэкенд упал между ордером и записью
в базу; позицию открыли руками на том же счёте. Такую позицию никто не ведёт — у неё нет
стопа и тейка бота, а при следующем входе Ghost Bot усреднит её.

Раз в WATCH_INTERVAL_SEC для реальных ботов без открытой позиции (Bybit и Cryptorg с ключом
Bybit) читаем позицию на бирже. Нашли — проблема «orphan» в bots-health → алерт в Telegram.
Сам сторож ничего не закрывает: чья это позиция и что с ней делать, решает человек.

Боты с открытой позицией не трогаем: их сверяет сам движок (EXCHANGE_CLOSED).
"""
import asyncio
import logging
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import and_, select

from app.core.database import AsyncSessionLocal
from app.services import exchange_issues

logger = logging.getLogger(__name__)

WATCH_INTERVAL_SEC = 120
REAL_EXCHANGES = ("bybit", "cryptorg")

GroupKey = Tuple[str, Optional[int], str, str]  # (биржа, аккаунт, монета, сторона)


def group_key(bot) -> GroupKey:
    account = bot.bybit_account_id if bot.exchange == "bybit" else bot.account_id
    return bot.exchange, account, bot.symbol, bot.side


def groups_to_check(bots: Iterable, open_bot_ids: Set[int]) -> Dict[GroupKey, List]:
    """Боты по (биржа, аккаунт, монета, сторона), где ни у кого нет открытой позиции.
    Одна позиция на бирже на группу: если у одного бота группы позиция есть,
    то, что на бирже, — его, и это не сирота."""
    groups: Dict[GroupKey, List] = {}
    busy: Set[GroupKey] = set()
    for b in bots:
        if b.exchange not in REAL_EXCHANGES or (b.config or {}).get("bot_type") == "straddle":
            continue
        key = group_key(b)
        if b.id in open_bot_ids or b.state in ("PYRAMIDING", "ENTRY", "EXIT"):
            busy.add(key)
        groups.setdefault(key, []).append(b)
    return {k: v for k, v in groups.items() if k not in busy}


def orphan_text(symbol: str, side: str, size: float) -> str:
    return (f"на бирже открыта позиция {symbol} {side} ({size:g} монет), а у бота её нет — "
            f"её никто не ведёт (ни стопа, ни тейка бота). Проверь счёт на бирже")


class ExchangeWatch:
    def __init__(self, interval: float = WATCH_INTERVAL_SEC):
        self.interval = interval
        self._task: Optional[asyncio.Task] = None
        # группы, где позиция без бота видна на прошлой проверке: сиротой считаем со второй
        # подряд — иначе вход, у которого ордер уже на бирже, а запись в базе ещё нет, даст ложный алерт
        self._seen: Set[GroupKey] = set()

    def start(self) -> None:
        if not self._task or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        await asyncio.sleep(30)  # дать движкам подняться после рестарта
        while True:
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[ExchangeWatch] {e}", exc_info=True)
            await asyncio.sleep(self.interval)

    async def check_once(self) -> int:
        """Возвращает число найденных сирот."""
        from app.adapters.executor_factory import build_executor
        from app.models import Bot, Position

        found = 0
        async with AsyncSessionLocal() as db:
            bots = (await db.execute(select(Bot).where(Bot.exchange.in_(REAL_EXCHANGES)))).scalars().all()
            if not bots:
                return 0
            open_ids = set((await db.execute(select(Position.bot_id).where(and_(
                Position.bot_id.in_([b.id for b in bots]), Position.is_open == True)))).scalars().all())  # noqa: E712
            groups = groups_to_check(bots, open_ids)
            checked = {b.id for members in groups.values() for b in members}
            # у бота появилась позиция — его «сирота» уже не сирота
            for b in bots:
                if b.id not in checked:
                    exchange_issues.clear(b.id, "orphan")

            seen_now: Set[GroupKey] = set()
            for key, members in groups.items():
                _, _, symbol, side = key
                try:
                    executor = await build_executor(members[0], db)
                    size = await executor.get_open_position_size(symbol, side)
                except Exception as e:
                    logger.warning(f"[ExchangeWatch] {symbol} {side}: {e}")
                    continue
                if size is None:
                    continue  # биржу не видно (Cryptorg без ключа, сбой API) — судить не о чем
                confirmed = size > 0 and key in self._seen
                if size > 0:
                    seen_now.add(key)
                for b in members:
                    if confirmed:
                        exchange_issues.report(b.id, "orphan", orphan_text(symbol, side, size))
                    elif size <= 0:
                        exchange_issues.clear(b.id, "orphan")
                if confirmed:
                    found += 1
                    logger.warning(f"[ORPHAN] {symbol} {side} size={size} bots={[b.id for b in members]}")
            self._seen = seen_now
        return found


exchange_watch = ExchangeWatch()
