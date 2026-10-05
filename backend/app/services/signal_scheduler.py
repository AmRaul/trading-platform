"""
SignalEntryScheduler — раз в минуту (сразу после закрытия свечи) проверяет
ботов в состоянии SIGNAL и открывает позицию, если сработал сигнал входа.

Свечи сигнального ТФ закрываются на границах интервала, поэтому проверка
идёт только для ботов, у которых на этой минуте закрылась свеча их ТФ, и
каждый бот проверяет каждую свечу один раз.
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

logger = logging.getLogger(__name__)

# Пауза после границы свечи: биржа отдаёт закрытую свечу с небольшой задержкой
CLOSE_DELAY_SEC = 5


class SignalEntryScheduler:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._check = CheckEntrySignalUseCase(BybitMarketDataAdapter())
        # bot_id -> timestamp закрытия последней проверенной свечи
        self._last_checked: Dict[int, int] = {}

    def start(self):
        if not self._task or self._task.done():
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
            result = await db.execute(select(Bot).where(Bot.state == "SIGNAL"))
            bots = result.scalars().all()

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

            logger.info(
                f"[SignalScheduler] bot={bot.id} {bot.symbol} {bot.side} "
                f"risk_zone={signal.risk_zone} trend_ok={signal.trend_ok} → {signal.reason}"
            )
            if signal.triggered:
                await self._enter(bot.id)

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
