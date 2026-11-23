"""
Интеграция: выход по каналу Donchian на настоящем Postgres + Redis, paper-исполнитель.
Бот в позиции (PYRAMIDING) → планировщик на закрытии часа видит close ниже минимума 10 дневок →
сделка закрыта с exit_reason SIGNAL_EXIT, бот снова ждёт сигнал (SIGNAL), повторной проверки той же
свечи нет. Свечи и тикер — подставные, всё остальное — как на проде.

Запуск (CI — job «Integration · backend»): python integration/donchian_exit.py
"""
import asyncio
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.redis import init_redis, close_redis
from app.models import User, Bot, Position, Order, Trade
from app.schemas.bot import StrategyConfig, EntrySignalConfig
from app.services.signal_scheduler import SignalEntryScheduler

DAY, HOUR = 86_400_000, 3_600_000


def ok(cond, msg):
    print(("OK  " if cond else "FAIL") + " " + msg)
    if not cond:
        raise SystemExit(1)


def daily(n=30, low=90.0):
    return [{"timestamp": i * DAY, "open": 100.0, "high": 110.0, "low": low, "close": 100.0, "volume": 1.0}
            for i in range(n)]


async def main():
    await init_redis()
    cfg = StrategyConfig(bot_type="pyramiding", order_count=1, entry_size_usdt=1000, step_percent=1.0, leverage=2,
                         pyramiding_multiplier=1.0, sl_initial=None, use_trailing=False, tp_percent=100, cycle=True,
                         entry_signal=EntrySignalConfig(type="donchian", timeframe="60", donchian_entry_days=20,
                                                        donchian_exit_days=10, trend_ema_period=None)).model_dump()
    async with AsyncSessionLocal() as db:
        u = User(username="donch", hashed_password="x"); db.add(u); await db.flush()
        b = Bot(user_id=u.id, exchange="paper", name="donch", symbol="ETHUSDT", side="LONG", config=cfg,
                state="PYRAMIDING", forward_test="donchian/long")
        db.add(b); await db.flush()
        p = Position(bot_id=b.id, symbol="ETHUSDT", side="LONG", is_open=True, average_price=100.0,
                     total_size=1000.0, current_sl=0.0, order_count=1, unrealized_pnl=0.0)
        db.add(p); await db.flush()
        db.add(Order(position_id=p.id, bot_id=b.id, symbol="ETHUSDT", side="BUY", size=1000.0, price=100.0,
                     order_number=1, status="FILLED"))
        await db.commit()
        bot_id = b.id

    now = 30 * DAY + HOUR + 5_000
    hour = lambda close: [{"timestamp": now - 5_000 - HOUR, "open": close, "high": close, "low": close,  # noqa: E731
                           "close": close, "volume": 1.0}]
    sched = SignalEntryScheduler()
    klines = {"close": 95.0}
    sched._check.market_data.get_klines = AsyncMock(
        side_effect=lambda s, tf, n: daily() if tf == "D" else hour(klines["close"]))

    with patch("app.services.bybit.bybit_client.get_ticker", AsyncMock(return_value={"lastPrice": "89.5"})):
        await sched.run_once(now)  # close 95 выше минимума 90 — держим
        async with AsyncSessionLocal() as db:
            ok((await db.get(Bot, bot_id)).state == "PYRAMIDING", "close выше минимума 10 дней — позиция открыта")
        ok("держим" in sched.last_result[bot_id]["reason"], f"причина: {sched.last_result[bot_id]['reason']}")

        klines["close"] = 89.0
        await sched.run_once(now)  # та же свеча — повторно не проверяется
        async with AsyncSessionLocal() as db:
            ok((await db.get(Bot, bot_id)).state == "PYRAMIDING", "та же часовая свеча второй раз не проверяется")

        await sched.run_once(now + HOUR)  # следующая свеча: close 89 < 90 — выход
        async with AsyncSessionLocal() as db:
            bot = await db.get(Bot, bot_id)
            trade = (await db.execute(select(Trade).where(Trade.bot_id == bot_id))).scalar_one_or_none()
            pos_open = (await db.execute(select(Position).where(Position.bot_id == bot_id,
                                                                Position.is_open == True))).scalar_one_or_none()  # noqa: E712
        ok(trade is not None and trade.exit_reason == "SIGNAL_EXIT", "сделка закрыта: SIGNAL_EXIT")
        ok(abs(trade.exit_price - 89.5) < 1e-9, f"выход по тикеру {trade.exit_price}")
        ok(trade.pnl < 0, f"PnL {trade.pnl:.2f} (вход 100 → выход 89.5, минус комиссии)")
        ok(pos_open is None and bot.state == "SIGNAL", "позиция закрыта, бот снова ждёт сигнал входа")

    await close_redis()
    print("donchian_exit: всё ОК")


if __name__ == "__main__":
    asyncio.run(main())
