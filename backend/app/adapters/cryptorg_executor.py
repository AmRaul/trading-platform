import asyncio
import logging
import time
from typing import Awaitable, Callable, Dict, Optional, Protocol, Tuple

from app.services.cryptorg import CryptorgClient, cryptorg_client

logger = logging.getLogger(__name__)

# Сколько ждать, пока команда Cryptorg появится на бирже, и как часто смотреть
CONFIRM_TIMEOUT_SEC = 20.0
CONFIRM_POLL_SEC = 1.5
# Размер позиции в монетах: меньше этого — считаем, что позиции нет (пыль округлений)
DUST = 1e-12

Pos = Tuple[float, float]  # (размер в монетах, средняя цена)


class PositionReader(Protocol):
    async def get_position(self, symbol: str, side: str) -> Optional[Pos]: ...


class CryptorgExecutorAdapter:
    """Cryptorg как ExchangeExecutor: команды — webhook Ghost Bot, проверка — API Bybit.

    Webhook только принимает команды: ни цены исполнения, ни того, исполнилась ли
    команда вообще, он не сообщает. Счёт Cryptorg «Bybit-ликвидность» — это
    субаккаунт Bybit, и его ключ (достаточно «только чтение») работает с API самого
    Bybit. С таким ключом (reader) каждая команда подтверждается позицией на бирже:

    - вход: на бирже не должно быть позиции этой стороны (иначе Ghost Bot усреднит
      чужую позицию); после команды ждём, пока позиция появится, и берём её среднюю;
    - добор: ждём роста размера; цена добора — из прироста стоимости позиции;
    - закрытие: успех, только когда позиции на бирже не осталось;
    - webhook упал по таймауту, а позиция на бирже появилась — это успех, иначе бот
      считал бы, что входа нет, и открыл бы второй.

    Без ключа — как раньше: ответ 200 считается исполнением, сверки нет (can_verify=False).
    """

    def __init__(
        self,
        client: CryptorgClient = None,
        reader: Optional[PositionReader] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        confirm_timeout: float = CONFIRM_TIMEOUT_SEC,
        poll: float = CONFIRM_POLL_SEC,
    ):
        self._client = client or cryptorg_client
        self._reader = reader
        self._sleep = sleep
        self._timeout = confirm_timeout
        self._poll = poll

    @property
    def can_verify(self) -> bool:
        return self._reader is not None

    async def _position(self, symbol: str, side: str) -> Optional[Pos]:
        try:
            return await self._reader.get_position(symbol, side)
        except Exception as e:
            logger.warning(f"[Cryptorg] чтение позиции {symbol} {side} через Bybit: {e}")
            return None

    async def _wait_for(self, symbol: str, side: str, done: Callable[[Pos], bool]) -> Optional[Pos]:
        """Опрос позиции, пока done(pos) не станет True или не выйдет время.
        Возвращает последнее прочитанное состояние (None — ни разу не прочитали)."""
        deadline = time.monotonic() + self._timeout
        last: Optional[Pos] = None
        while True:
            pos = await self._position(symbol, side)
            if pos is not None:
                last = pos
                if done(pos):
                    return pos
            if time.monotonic() >= deadline:
                return last
            await self._sleep(self._poll)

    async def open_position(
        self,
        symbol: str,
        side: str,
        order_volume_usdt: float,
        leverage: int,
        sl_percent: float,
        tp_percent: float,
    ) -> Dict:
        if self._reader:
            before = await self._position(symbol, side)
            if before is None:
                return {"success": False, "error": "Cryptorg: не удалось прочитать позицию на Bybit — вход отменён"}
            if before[0] > DUST:
                return {"success": False, "error": (
                    f"Cryptorg: на бирже уже открыта позиция {symbol} {side.upper()} "
                    f"({before[0]:g} @ {before[1]:g}) — вход отменён, иначе Ghost Bot её усреднит")}

        sent = await self._client.open_position(
            symbol=symbol, side=side, order_volume_usdt=order_volume_usdt,
            leverage=leverage, sl_percent=sl_percent, tp_percent=tp_percent,
        )
        if not self._reader:
            return sent

        pos = await self._wait_for(symbol, side, lambda p: p[0] > DUST)
        if pos and pos[0] > DUST:
            if not sent.get("success"):
                logger.warning(f"[Cryptorg] webhook open {symbol} ответил ошибкой, но позиция на бирже есть — принимаем")
            return {**sent, "success": True, "avg_price": pos[1], "exchange_size": pos[0]}
        return {"success": False, "error": (
            f"Cryptorg: позиция {symbol} {side.upper()} не появилась на бирже за {self._timeout:.0f} с "
            f"(webhook: {'принят' if sent.get('success') else 'ошибка'})")}

    async def add_to_position(self, symbol: str, side: str, amount_usdt: float) -> Dict:
        before: Optional[Pos] = None
        if self._reader:
            before = await self._position(symbol, side)
            if before is None:
                return {"success": False, "error": "Cryptorg: не удалось прочитать позицию на Bybit — добор отменён"}
            if before[0] <= DUST:
                return {"success": False, "error": f"Cryptorg: позиции {symbol} {side.upper()} на бирже нет — добор отменён"}

        sent = await self._client.add_to_position(symbol=symbol, side=side, amount_usdt=amount_usdt)
        if not self._reader:
            return sent

        old_size, old_avg = before
        pos = await self._wait_for(symbol, side, lambda p: p[0] > old_size * (1 + 1e-9) + DUST)
        if pos and pos[0] > old_size * (1 + 1e-9) + DUST:
            added = pos[0] - old_size
            fill_price = (pos[0] * pos[1] - old_size * old_avg) / added
            return {**sent, "success": True, "avg_price": pos[1], "fill_price": fill_price, "exchange_size": pos[0]}
        return {"success": False, "error": (
            f"Cryptorg: добор {symbol} не исполнился на бирже за {self._timeout:.0f} с "
            f"(webhook: {'принят' if sent.get('success') else 'ошибка'})")}

    async def close_position(self, symbol: str, side: str, quantity: Optional[float] = None) -> Dict:
        sent = await self._client.close_position(symbol=symbol, side=side, quantity=quantity)
        if not self._reader:
            return sent
        pos = await self._wait_for(symbol, side, lambda p: p[0] <= DUST)
        if pos is not None and pos[0] <= DUST:
            return {**sent, "success": True}
        left = f"осталось {pos[0]:g}" if pos else "позицию не удалось прочитать"
        return {"success": False, "error": (
            f"Cryptorg: позиция {symbol} {side.upper()} на бирже не закрылась за {self._timeout:.0f} с — {left} "
            f"(webhook: {'принят' if sent.get('success') else 'ошибка'})")}

    async def get_open_position_size(self, symbol: str, side: str) -> Optional[float]:
        if not self._reader:
            # Ghost Bot webhook только отправляет команды; без ключа Bybit сверка невозможна
            return None
        pos = await self._position(symbol, side)
        return None if pos is None else pos[0]

    async def update_stop_and_tp(
        self,
        symbol: str,
        side: str,
        sl_percent: Optional[float],
        tp_percent: Optional[float],
    ) -> Dict:
        # PositionCalculator.calculate_sl_percent() encodes direction as sign
        # (positive = stop below entry) for Bybit's absolute-price math, which
        # needs the offset direction in a single number. Cryptorg's webhook
        # has no such convention — "value" is always a plain positive percent
        # and direction comes from "strategy" (long/short) — so a raw negative
        # string here (e.g. "-2.0") is a malformed stop Cryptorg never expects,
        # which is what let SL/TP misfire immediately after order#3/#4 filled.
        return await self._client.update_stop_and_tp(
            symbol=symbol,
            side=side,
            sl_percent=abs(sl_percent) if sl_percent is not None else None,
            tp_percent=tp_percent,
        )
