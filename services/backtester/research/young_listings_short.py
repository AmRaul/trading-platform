"""Гипотеза (журнал kandle #10): шорт альтов работает на молодых монетах (после листинга падают).
Проверка на монетах, которых не было в отборе: листинг на Bybit после 2024-07.

Всё записано ДО загрузки данных (2026-11-25):
  Выборка: USDT-перпетуалы Bybit (linear) с launchTime в [2024-07-01, 2025-07-01); из них 30 с наибольшим
  оборотом за первые 30 дней после листинга (известно в момент торговли, сегодняшний объём не используется).
  Стратегия: база alt_short без изменений (4h режим вниз + разворот Supertrend 15m, 4 ордера, стоп 2%,
  трейлинг 1U), торгует с листинга до 2026-10-02 (первые ~33 дня уходят на прогрев EMA200 4h).
  Портфель: 10 слотов по $1000 (депозит $10 000), первые пришедшие сигналы.
  Проходит, если ВСЕ:
    1) ratio портфеля (годовая / макс. просадка от депозита) >= 0.5 на 2024-08-01..2026-10-02;
    2) >= 55% монет с положительным итогом;
    3) без 3 лучших монет сумма PnL всё ещё > 0;
    4) корреляция месячного PnL с текущим портфелем (шорт 5 альтов + Donchian лонг) <= 0.3.
"""
import json
import time
import numpy as np, pandas as pd
import requests
import hypothesis_runner as hr
import short_portfolio as sp

import os

# Прогон #11: листинги 2024-07..2025-07, торговля до конца данных (по умолчанию).
# Прогон #12 (критерии те же 4, записаны 2026-11-25 до загрузки): листинги 2025-07-01..2026-04-01
# (у каждой >= 6 мес. до 2026-10-02), торговля только первые 180 дней после первой свечи, период с 2025-08-01:
#   YL_A=2025-07-01 YL_B=2026-04-01 YL_TEST_FROM=2025-08-01 YL_MAX_AGE_DAYS=180 YL_OUT=young_listings_180d_new
A, B = pd.Timestamp(os.environ.get("YL_A", "2024-07-01")), pd.Timestamp(os.environ.get("YL_B", "2025-07-01"))
N, SLOTS, SLOT = 30, 10, 1000.0
TEST_FROM = pd.Timestamp(os.environ.get("YL_TEST_FROM", "2024-08-01"))
MAX_AGE = int(os.environ.get("YL_MAX_AGE_DAYS", "0"))  # 0 — без ограничения
OUT = os.environ.get("YL_OUT", "young_listings_short")
API = "https://api.bybit.com/v5/market"


def get(path, params):
    for i in range(5):
        try:
            return requests.get(f"{API}/{path}", params=params, timeout=20).json()
        except requests.RequestException:
            time.sleep(2 * (i + 1))
    raise RuntimeError(path)


def universe():
    out, cursor = [], ""
    while True:
        body = get("instruments-info", {"category": "linear", "limit": 1000, "cursor": cursor})
        res = body["result"]
        out += res["list"]
        cursor = res.get("nextPageCursor") or ""
        if not cursor:
            break
    rows = []
    for x in out:
        if x.get("quoteCoin") != "USDT" or x.get("contractType") != "LinearPerpetual" or not x["symbol"].endswith("USDT"):
            continue
        t = pd.Timestamp(int(x["launchTime"]), unit="ms")
        if A <= t < B:
            rows.append((x["symbol"][:-4], t))
    return rows


def first_month_turnover(coin, launch):
    end = int((launch + pd.Timedelta(days=31)).timestamp() * 1000)
    body = get("kline", {"category": "linear", "symbol": f"{coin}USDT", "interval": "D", "limit": 31, "end": end})
    rows = (body.get("result") or {}).get("list") or []
    rows = [r for r in rows if pd.Timestamp(int(r[0]), unit="ms") < launch + pd.Timedelta(days=30)]
    return sum(float(r[6]) for r in rows)


def coin_trades(coin, p):
    def cfg(df, step):
        import donchian_pyramid as dp
        c = dp.bot_config(0, p["order_count"], False, None)
        c.update(entry_size_usdt=p["first_order"], tp_percent=p["tp_percent"], step_percent=p["step_percent"],
                 sl_initial=p["sl_percent"], sl_after_order3=p["sl_percent"],
                 trailing_percent=round(dp.vol_unit(df) * p["trailing_u"], 1))
        return c
    return hr.alt_coin_trades(coin, p, cfg, "SHORT")


if __name__ == "__main__":
    import new_ideas as ni
    cands = universe()
    print("listed in window:", len(cands), flush=True)
    turn = []
    for coin, t in cands:
        try:
            turn.append((first_month_turnover(coin, t), coin, t))
        except Exception as e:
            print("skip", coin, e)
        time.sleep(0.05)
    picked = sorted(turn, reverse=True)[:N]
    print("picked:", [(c, str(t.date()), round(v / 1e6)) for v, c, t in picked], flush=True)

    # загрузка 15m и прогон — в hr/sp подменяем загрузчик, как run_pyramid
    hr.run_pyramid  # noqa: B018 — импорт модулей исследования
    import mrc_supertrend_pyramid as msp, trend_pullback_pyramid as tpp
    load = lambda coin: (pd.read_csv(hr.csv_path(coin), parse_dates=["timestamp"])  # noqa: E731
                         .sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True))
    msp.load_15m = sp.load_15m = tpp.load_15m = load
    p = hr.resolve("alt_short", {})
    import donchian_pyramid as dp
    dp.DEPOSIT = SLOT * SLOTS
    sp.ENTRY = p["first_order"]

    by_coin = {}
    for _, coin, t in picked:
        path = hr.DATA / f"{coin}USDT_15m_bybit_futures.csv"
        if not path.exists():
            try:
                hr.download_bybit_15m(coin, start=t - pd.Timedelta(days=1), end=hr.END + pd.Timedelta(days=1))
            except RuntimeError as e:  # нет истории на бирже — монету не считаем (до 2026-10 она в выборке)
                print("no data", coin, e, flush=True)
                continue
        p["coins"] = [coin]
        tr = coin_trades(coin, p)
        if MAX_AGE:
            first = pd.read_csv(hr.csv_path(coin), usecols=["timestamp"], nrows=1, parse_dates=["timestamp"]).timestamp[0]
            tr = [x for x in tr if sp.GRID_IDX[x[0]] < first + pd.Timedelta(days=MAX_AGE)]
        by_coin[coin] = tr
        print(coin, "trades", len(by_coin[coin]), flush=True)

    pnl, taken, _ = sp.portfolio(by_coin, SLOTS, "first")
    dep = SLOT * SLOTS
    eq = pd.Series(dep + pnl, index=sp.GRID_IDX)
    idx = sp.GRID_IDX
    trades = pd.DataFrame([{"coin": c, "exit": idx[t[1]], "pnl": t[2], "orders": t[3]} for c, t in taken])
    s = hr.period_stats(eq, dep, trades, TEST_FROM, hr.END)
    per = trades.groupby("coin")["pnl"].sum().sort_values()
    without_top3 = float(per.iloc[:-3].sum())

    port, _ = ni.current_portfolio()
    pm = ni.monthly(port[(port.index >= TEST_FROM) & (port.index < hr.END)])
    ym = ni.monthly(eq[(eq.index >= TEST_FROM) & (eq.index < hr.END)])
    j = pd.concat([pm, ym], axis=1, join="inner").dropna()
    corr = round(float(j.iloc[:, 0].corr(j.iloc[:, 1])), 2)

    out = {"stats": s, "coins": len(per), "positive_pct": round(float((per > 0).mean() * 100)),
           "sum_pnl": round(float(per.sum())), "without_top3": round(without_top3), "corr": corr,
           "per_coin": {k: round(float(v)) for k, v in per.items()},
           "monthly_pct": {str(k.date()): round(float(v) / dep * 100, 1) for k, v in ym.items()}}
    out["passed"] = bool(s.get("ratio", -9) >= 0.5 and out["positive_pct"] >= 55 and without_top3 > 0 and corr <= 0.3)
    print(json.dumps(out, indent=1), flush=True)
    json.dump(out, open(f"{OUT}_results.json", "w"), indent=1)
