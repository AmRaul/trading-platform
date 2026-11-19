"""
Интеграция: движок зарегистрированного бота на настоящем Postgres + Redis.
Моки (tests/) не ловят поведение SQLAlchemy — протухшие после rollback объекты,
сессию, которую держат днями. Здесь — настоящие сессии, alembic-схема, paper-исполнитель.

Запуск (CI — job «Integration · backend»):
    alembic upgrade head && python integration/engine_session.py
Нужны DATABASE_URL, REDIS_URL, SECRET_KEY; база — пустая тестовая.
"""
import asyncio
from datetime import datetime, timezone
from sqlalchemy import select, text
from app.core.database import AsyncSessionLocal, engine as sa_engine
from app.models import User, Bot, Position, Order, Trade
from app.services.strategy import StrategyEngine, BotState
from app.schemas.bot import StrategyConfig
from app.core.redis import init_redis, close_redis

def ok(cond, msg):
    print(("OK  " if cond else "FAIL") + " " + msg)
    if not cond: raise SystemExit(1)

def checked_out():
    return sa_engine.pool.checkedout()

async def main():
    await init_redis()
    cfg = StrategyConfig(entry_size_usdt=100, pyramiding_multiplier=1.0, order_count=4, step_percent=2.0,
                         sl_initial=2.0, sl_after_order3=1.0, use_trailing=True, trailing_percent=1.0,
                         leverage=1).model_dump()
    async with AsyncSessionLocal() as db:
        u = User(username="t", hashed_password="x"); db.add(u); await db.flush()
        b = Bot(user_id=u.id, exchange="paper", name="it", symbol="SOLUSDT", side="LONG", config=cfg, state="PYRAMIDING")
        db.add(b); await db.flush()
        p = Position(bot_id=b.id, symbol="SOLUSDT", side="LONG", is_open=True, average_price=100.0, total_size=100.0,
                     current_sl=98.0, order_count=1, unrealized_pnl=0.0)
        db.add(p); await db.flush()
        db.add(Order(position_id=p.id, bot_id=b.id, symbol="SOLUSDT", side="BUY", size=100.0, price=100.0,
                     order_number=1, status="FILLED"))
        await db.commit()
        bot_id, pos_id = b.id, p.id

    e = StrategyEngine(bot_id)
    await e.initialize()
    ok(e._op_db is None and checked_out() == 0, "после initialize сессия закрыта, соединение возвращено в пул")
    ok(e.position is not None and len(e.calculator.orders) == 1, "позиция и ордера восстановлены")
    try:
        e.db
        ok(False, "db вне операции должен падать")
    except RuntimeError:
        ok(True, "обращение к db вне операции — явная ошибка, а не тихая долгая сессия")

    # тики: стоп подтягивается в памяти, БД не трогается
    for price in (100.5, 101.0, 101.5):
        await e.on_price_update(price)
    ok(checked_out() == 0, "тики без событий не держат соединение")
    e.position.current_sl = 99.25  # как сделал бы трейлинг на тике — изменение только в памяти
    sl_mem = e.position.current_sl
    async with AsyncSessionLocal() as db:
        sl_db = (await db.get(Position, pos_id)).current_sl
    ok(sl_mem > 98.0 and sl_db == 98.0, f"трейлинг в памяти {sl_mem:.4f}, в базе пока {sl_db} (как и раньше)")

    # изменение из API в другой сессии (is_bot_managed) — движок не затирает чужие поля
    async with AsyncSessionLocal() as db:
        await db.execute(text("update bots set name='renamed' where id=:i"), {"i": bot_id}); await db.commit()

    # операция с commit: прикреплённая позиция сохраняет стоп из памяти
    async with e.session() as db:
        await db.commit()
    async with AsyncSessionLocal() as db:
        ok(abs((await db.get(Position, pos_id)).current_sl - sl_mem) < 1e-9, "commit операции сохранил стоп из памяти")
        ok((await db.get(Bot, bot_id)).name == "renamed", "чужое изменение (name) не затёрто старым значением")

    # rollback внутри операции: объекты не протухают, перечитываются из базы
    async with e.session() as db:
        e.bot.limit_entry_price = 1.0
        await db.flush()
        await db.rollback()
    ok(e.bot.limit_entry_price is None and e.position.current_sl == sl_mem, "после rollback объекты целы и равны базе")
    await e.on_price_update(101.6)
    ok(True, "тик после rollback не падает (раньше — протухшие атрибуты в долгой сессии)")

    # добор с ошибкой внутри use case → rollback в движке → объекты перечитаны, тик не падает
    orig = e._add_order_uc.execute
    async def boom(*a, **k):
        await e.db.flush(); raise RuntimeError("биржа отвалилась")
    e._add_order_uc.execute = boom
    await e._add_pyramiding_order(102.0)
    e._add_order_uc.execute = orig
    await e.on_price_update(101.7)
    ok(e.position.is_open and checked_out() == 0, "добор с ошибкой: rollback, позиция цела, тики идут")

    # добор по-настоящему: цена 104 → второй ордер в базе
    await e._add_pyramiding_order(102.0)
    async with AsyncSessionLocal() as db:
        n = len((await db.execute(select(Order).where(Order.position_id == pos_id))).scalars().all())
    ok(n == 2 and len(e.calculator.orders) == 2, f"добор записан через сессию операции (ордеров {n})")

    # закрытие по стопу
    await e._close_position(95.0, "SL_HIT")
    async with AsyncSessionLocal() as db:
        pos = await db.get(Position, pos_id)
        trades = (await db.execute(select(Trade).where(Trade.bot_id == bot_id))).scalars().all()
        bot = await db.get(Bot, bot_id)
    ok(not pos.is_open and len(trades) == 1 and trades[0].exit_reason == "SL_HIT", "закрытие: позиция закрыта, сделка записана")
    ok(e.position is None and e.current_state == BotState.IDLE, f"движок в IDLE, bot.state в базе = {bot.state}")
    ok(checked_out() == 0, "все соединения возвращены")
    await close_redis()
    await sa_engine.dispose()

asyncio.run(main())
