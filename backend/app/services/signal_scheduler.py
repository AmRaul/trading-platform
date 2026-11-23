"""
SignalEntryScheduler — раз в минуту (сразу после закрытия свечи) проверяет
ботов в состоянии SIGNAL и открывает позицию, если сработал сигнал входа.

Свечи сигнального ТФ закрываются на границах интервала, поэтому проверка
идёт только для ботов, у которых на этой минуте закрылась свеча их ТФ, и
каждый бот проверяет каждую свечу один раз.

Боты с выходом по сигналу (entry_signal.type = donchian) в позиции (PYRAMIDING) проверяются
так же — на закрытии каждой свечи своего ТФ — и закрываются по рынку, если сработал выход.
"""
import asyncio
import json
import logging
import time
from typing import Dict, Tuple

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.adapters.bybit_market_data import BybitMarketDataAdapter
from app.application.signals.check_entry_signal import CheckEntrySignalUseCase, INTERVAL_MS
from app.domain.signals.entry_signal import has_signal_exit

logger = logging.getLogger(__name__)

# Пауза после границы свечи: биржа отдаёт закрытую свечу с небольшой задержкой
CLOSE_DELAY_SEC = 5


class SignalEntryScheduler:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._check = CheckEntrySignalUseCase(BybitMarketDataAdapter())
        # bot_id -> timestamp закрытия последней проверенной свечи
        self._last_checked: Dict[int, int] = {}
        # bot_id -> {checked_at_ms, reason, triggered} — для проверки «жив ли бот» (bots-health)
        self.last_result: Dict[int, dict] = {}
        self.started_ms: int | None = None

    @property
    def running(self) -> bool:
        return bool(self._task and not self._task.done())

    def start(self):
        if not self._task or self._task.done():
            self.started_ms = int(time.time() * 1000)
            self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()

    async def _loop(self):
        logger.info("[SignalScheduler] started")
        while True:
            try:
                now = time.time()
                await asyncio.sleep(60 - now % 60 + CLOSE_DELAY_SEC)
                await self.run_once(int(time.time() * 1000))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SignalScheduler] tick error: {e}", exc_info=True)

    async def run_once(self, now_ms: int):
        from app.models import Bot

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Bot).where(Bot.state.in_(("SIGNAL", "PYRAMIDING"))))
            all_bots = result.scalars().all()
        bots = [b for b in all_bots if b.state == "SIGNAL"]
        await self._check_exits([b for b in all_bots if b.state == "PYRAMIDING"
                                 and has_signal_exit((b.config or {}).get("entry_signal"))], now_ms)

        # Одинаковые symbol/side/конфиг сигнала считаем один раз
        cache: Dict[Tuple[str, str, str], object] = {}
        for bot in bots:
            cfg = (bot.config or {}).get("entry_signal")
            if not cfg:
                continue
            interval = INTERVAL_MS[cfg.get("timeframe", "15")]
            last_close = now_ms - now_ms % interval
            if self._last_checked.get(bot.id) == last_close:
                continue
            self._last_checked[bot.id] = last_close

            key = (bot.symbol, bot.side, json.dumps(cfg, sort_keys=True))
            if key not in cache:
                cache[key] = await self._check.execute(bot.symbol, bot.side, cfg, now_ms)
            signal = cache[key]
            if signal.data_missing:
                # вход Supertrend — разворот ровно на последней свече: пропуск проверки = пропуск сделки.
                # Свеча та же до следующего закрытия, поэтому повторяем на следующем тике.
                self._last_checked.pop(bot.id, None)
            self.last_result[bot.id] = {
                "checked_at_ms": now_ms, "reason": signal.reason, "triggered": signal.triggered,
                "risk_zone": signal.risk_zone, "trend_ok": signal.trend_ok,
            }

            logger.info(
                f"[SignalScheduler] bot={bot.id} {bot.symbol} {bot.side} "
                f"risk_zone={signal.risk_zone} trend_ok={signal.trend_ok} → {signal.reason}"
            )
            if signal.triggered:
                await self._enter(bot.id)

    async def _check_exits(self, bots, now_ms: int):
        for bot in bots:
            cfg = bot.config["entry_signal"]
            interval = INTERVAL_MS[cfg.get("timeframe", "15")]
            last_close = now_ms - now_ms % interval
            key = ("exit", bot.id)
            if self._last_checked.get(key) == last_close:
                continue
            self._last_checked[key] = last_close
            try:
                signal = await self._check.execute_exit(bot.symbol, bot.side, cfg, now_ms)
            except Exception as e:
                logger.error(f"[SignalScheduler] exit check bot={bot.id} failed: {e}")
                self._last_checked.pop(key, None)
                continue
            if signal.data_missing:
                self._last_checked.pop(key, None)
            self.last_result[bot.id] = {"checked_at_ms": now_ms, "reason": signal.reason,
                                        "triggered": signal.triggered, "exit_level": signal.trend_ema}
            logger.info(f"[SignalScheduler] bot={bot.id} {bot.symbol} {bot.side} exit check → {signal.reason}")
            if signal.triggered:
                await self._exit(bot.id, signal.trend_close)

    async def _exit(self, bot_id: int, price: float):
        from app.services.strategy import StrategyEngine

        async with AsyncSessionLocal() as db:
            engine = StrategyEngine(bot_id, db)
            await engine.initialize()
            result = await engine.signal_exit(price)
        if result.get("success"):
            logger.info(f"[SIGNAL_EXIT] bot={bot_id} closed @ {result.get('exit_price')}")
        else:
            logger.error(f"[SIGNAL_EXIT] bot={bot_id} failed: {result.get('error')}")

    async def _enter(self, bot_id: int):
        from app.services.strategy import StrategyEngine

        async with AsyncSessionLocal() as db:
            engine = StrategyEngine(bot_id, db)
            await engine.initialize()
            result = await engine.signal_entry()
        if result.get("success"):
            logger.info(f"[SIGNAL_ENTRY] bot={bot_id} opened @ {result.get('price')}")
        else:
            logger.error(f"[SIGNAL_ENTRY] bot={bot_id} failed: {result.get('error')}")


signal_scheduler = SignalEntryScheduler()
