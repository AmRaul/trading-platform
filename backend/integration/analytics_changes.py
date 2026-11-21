"""
Интеграция на настоящем Postgres: разметка комплектов форвард-теста миграцией,
/api/analytics/forward-test и /api/analytics/changes (what_changed) со снимками.

Запуск (CI — job «Integration · backend»), на пустой базе:
    alembic upgrade e6f7a8b9c0d1 && python integration/analytics_changes.py
Скрипт сам вставляет ботов на старой схеме и докатывает миграции до head.
"""
import asyncio
import subprocess
from datetime import datetime, timedelta, timezone

from sqlalchemy import text


def ok(cond, msg):
    print(("OK  " if cond else "FAIL") + " " + msg)
    if not cond:
        raise SystemExit(1)


NAMES = [
    ("MRC DCA · BTC 15m Long · Консервативный", "BTCUSDT", "LONG", "paper", "portfolio/mrc"),
    ("Шорт альтов · пирамидинг · 5 монет · Консервативный · SOLUSDT", "SOLUSDT", "SHORT", "paper", "portfolio/short"),
    ("Шорт альтов · пирамидинг · 5 монет · Тейк 6% · XRPUSDT", "XRPUSDT", "SHORT", "paper", "take6/short"),
    ("HYPEUSDT", "HYPEUSDT", "LONG", "paper", None),
    ("Шорт альтов · пирамидинг · 5 монет · Консервативный · SOLUSDT", "SOLUSDT", "SHORT", "cryptorg", None),
]


async def seed_old_schema():
    from app.core.database import engine
    async with engine.begin() as conn:
        uid = (await conn.execute(text(
            "insert into users (username, hashed_password) values ('it', 'x') returning id"))).scalar()
        for name, symbol, side, exchange, _ in NAMES:
            await conn.execute(text(
                "insert into bots (user_id, exchange, name, symbol, side, config, state, is_active, total_pnl) "
                "values (:u, :e, :n, :s, :sd, '{}', 'SIGNAL', false, 0)"),
                {"u": uid, "e": exchange, "n": name, "s": symbol, "sd": side})
    await engine.dispose()
    return uid


async def main():
    uid = await seed_old_schema()
    subprocess.run(["alembic", "upgrade", "head"], check=True, capture_output=True)

    from app.api.routes.analytics import changes, forward_test
    from app.core.database import AsyncSessionLocal
    from app.core.redis import close_redis, init_redis
    from app.models import Bot, Position, Trade, User
    from sqlalchemy import select

    await init_redis()
    async with AsyncSessionLocal() as db:
        bots = (await db.execute(select(Bot).order_by(Bot.id))).scalars().all()
        ok([b.forward_test for b in bots] == [n[4] for n in NAMES],
           "миграция разметила бумажных ботов по комплектам, реальный и ручной — без комплекта")
        user = await db.get(User, uid)

        sets = (await forward_test(db=db, current_user=user))["sets"]
        ok([b["name"] for b in sets["portfolio"]["parts"]["short"]["bots"]] == [NAMES[1][0]]
           and sets["portfolio"]["expectations"]["max_drawdown_pct"] == 14.4,
           "forward-test: ожидания и боты частей")

        bots[1].name = "переименованный шорт"
        await db.commit()
        sets = (await forward_test(db=db, current_user=user))["sets"]
        ok(sets["portfolio"]["parts"]["short"]["bots"][0]["name"] == "переименованный шорт",
           "переименование не выкидывает бота из комплекта")

        first = await changes(since=None, save=True, db=db, current_user=user)
        ok(first["compared_with_snapshot"] is None and "note" in first, "первый вызов: снимков нет, только события")

        # между проверками: бот вошёл, другой закрыл сделку
        sol = bots[1]
        sol.state = "PYRAMIDING"
        db.add(Position(bot_id=sol.id, symbol="SOLUSDT", side="SHORT", is_open=True, average_price=73.0,
                        total_size=250.0, current_sl=74.46, order_count=1, unrealized_pnl=1.5))
        now = datetime.now(timezone.utc)
        closed_pos = Position(bot_id=bots[2].id, symbol="XRPUSDT", side="SHORT", is_open=False, average_price=0.962,
                              total_size=1000.0, order_count=4, opened_at=now - timedelta(days=2), closed_at=now)
        db.add(closed_pos)
        await db.flush()
        db.add(Trade(bot_id=bots[2].id, position_id=closed_pos.id, symbol="XRPUSDT", side="SHORT", entry_price=0.97,
                     average_price=0.962, total_size=1000, exit_price=0.904, exit_reason="TP_HIT", pnl=59.07,
                     pnl_percent=6.01, total_orders=4, opened_at=now - timedelta(hours=20)))
        bots[2].total_pnl = 59.07
        await db.commit()

        second = await changes(since=None, save=True, db=db, current_user=user)
        ok(second["compared_with_snapshot"] is not None, "второй вызов сравнивает со снимком первого")
        ok([e["bot_id"] for e in second["events"]["entries"]] == [sol.id], "вход виден в событиях")
        ok([(e["exit_reason"], e["pnl"]) for e in second["events"]["exits"]] == [("TP_HIT", 59.07)],
           "закрытая сделка с PnL")
        ok(second["state_changes"] == [{"bot_id": sol.id, "name": "переименованный шорт",
                                        "from": "SIGNAL", "to": "PYRAMIDING"}], "смена состояния")
        ok(second["totals"]["realized_pnl"]["change"] == 59.07, "реализованный PnL вырос на сделку")

        pos = (await db.execute(select(Position).where(Position.bot_id == sol.id))).scalar_one()
        pos.current_sl = 73.9
        pos.unrealized_pnl = 4.0
        await db.commit()
        third = await changes(since=None, save=False, db=db, current_user=user)
        ok(third["events"]["entries"] == [] and third["events"]["exits"] == [],
           "третий вызов: события только после прошлой проверки")
        ok([(m["from"], m["to"]) for m in third["stop_moves"]] == [(74.46, 73.9)], "сдвиг стопа")
        ok(third["unrealized_changes"][0]["change"] == 2.5, "изменение плавающего PnL")
        again = await changes(since=None, save=False, db=db, current_user=user)
        ok(again["stop_moves"] == third["stop_moves"], "save=False не сдвигает точку прошлой проверки")
    await close_redis()
    print("ALL OK")


if __name__ == "__main__":
    asyncio.run(main())
