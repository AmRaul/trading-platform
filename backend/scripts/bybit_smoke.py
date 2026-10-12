"""
Проверка Bybit-аккаунта платформы реальными ордерами — тем же адаптером, что у ботов.

Открывает маленький шорт, ставит стоп, делает добор, переставляет стоп,
закрывает позицию. После каждого шага сверяет состояние с биржей.
По умолчанию работает только на testnet-аккаунте.

На сервере:
    docker compose exec backend python -m scripts.bybit_smoke --account-id 1
    docker compose exec backend python -m scripts.bybit_smoke --account-id 1 --symbol XRPUSDT --usdt 10
"""
import argparse
import asyncio
import sys

from sqlalchemy import select

from app.adapters.bybit_executor import BybitExecutorAdapter
from app.core.database import AsyncSessionLocal
from app.core.encryption import decrypt
from app.models.bybit_account import BybitAccount

SL_PERCENT = 2.0
failed = False


def report(ok: bool, step: str, detail: str = ""):
    global failed
    failed |= not ok
    print(f"{'OK  ' if ok else 'FAIL'} {step}" + (f" — {detail}" if detail else ""), flush=True)


async def position(ex: BybitExecutorAdapter, symbol: str) -> dict:
    resp = await ex._run(lambda: ex._client.get_positions(category="linear", symbol=symbol))
    rows = [r for r in resp.get("result", {}).get("list", []) if float(r.get("size") or 0) > 0]
    return rows[0] if rows else {}


async def check_stop(ex, symbol, step):
    pos = await position(ex, symbol)
    avg, sl = float(pos.get("avgPrice") or 0), float(pos.get("stopLoss") or 0)
    want = avg * (1 + SL_PERCENT / 100)
    report(bool(sl) and abs(sl / want - 1) < 0.001, step,
           f"avg {avg}, стоп {sl or 'нет'} (ожидался ≈{want:.6g}), тейк {pos.get('takeProfit') or 'нет'}")


async def main(account_id: int, symbol: str, usdt: float, mainnet: bool):
    async with AsyncSessionLocal() as db:
        acc = (await db.execute(select(BybitAccount).where(BybitAccount.id == account_id))).scalar_one_or_none()
    if not acc:
        sys.exit(f"Bybit-аккаунт {account_id} не найден")
    if not acc.testnet and not mainnet:
        sys.exit(f"Аккаунт «{acc.name}» — не testnet. Для реальных денег добавьте --mainnet")
    print(f"Аккаунт «{acc.name}» ({'testnet' if acc.testnet else 'MAINNET'}), {symbol}, ордер {usdt} USDT\n")
    ex = BybitExecutorAdapter(decrypt(acc.api_key), decrypt(acc.api_secret), testnet=acc.testnet)

    bal = await ex._run(lambda: ex._client.get_wallet_balance(accountType="UNIFIED", coin="USDT"))
    report(bal.get("retCode") == 0, "Ключи и баланс",
           bal.get("retMsg") if bal.get("retCode") else
           f"USDT {bal['result']['list'][0].get('totalAvailableBalance') or bal['result']['list'][0].get('totalEquity')}")
    if failed:
        return

    if await position(ex, symbol):
        sys.exit(f"По {symbol} уже есть открытая позиция — скрипт её не трогает. Выберите другую монету")

    inst = await ex._instrument(symbol)
    report(inst is not None, "Параметры инструмента",
           f"шаг лота {inst[0]}, мин. лот {inst[1]}, шаг цены {inst[2]}" if inst else "")
    if not inst:
        return

    opened = False
    try:
        r = await ex.open_position(symbol, "short", usdt, 10, SL_PERCENT, None)
        report(r.get("success"), "Открытие шорта по рынку", r.get("error", ""))
        if not r.get("success"):
            return
        opened = True
        pos = await position(ex, symbol)
        report(pos.get("side") == "Sell", "Позиция на бирже",
               f"сторона {pos.get('side')}, размер {pos.get('size')}, плечо {pos.get('leverage')}, "
               f"positionIdx {pos.get('positionIdx')}")
        await check_stop(ex, symbol, "Стоп после входа")

        r = await ex.add_to_position(symbol, "short", usdt)
        report(r.get("success"), "Добор по рынку", r.get("error", ""))
        size = float((await position(ex, symbol)).get("size") or 0)
        report(size > float(pos.get("size") or 0), "Размер вырос после добора", f"{pos.get('size')} → {size}")

        r = await ex.update_stop_and_tp(symbol, "short", SL_PERCENT, None)
        report(r.get("success"), "Перестановка стопа от новой средней (без тейка)", r.get("error", ""))
        await check_stop(ex, symbol, "Стоп после добора")
    finally:
        if opened:
            r = await ex.close_position(symbol, "short")
            report(r.get("success"), "Закрытие позиции", r.get("error", ""))
            left = await position(ex, symbol)
            report(not left, "Позиция закрыта на бирже",
                   f"осталось {left.get('size')} — закройте вручную!" if left else "")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--account-id", type=int, required=True)
    ap.add_argument("--symbol", default="SOLUSDT")
    ap.add_argument("--usdt", type=float, default=20.0)
    ap.add_argument("--mainnet", action="store_true", help="разрешить аккаунт с реальными деньгами")
    args = ap.parse_args()
    asyncio.run(main(args.account_id, args.symbol.upper(), args.usdt, args.mainnet))
    print("\nИтог:", "есть ошибки" if failed else "всё работает")
    sys.exit(1 if failed else 0)
