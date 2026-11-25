"""Шорт альтов (база alt_short без изменений) на других монетах.

Правило отбора записано ДО прогона (2026-11-25):
  монета проходит, если на TRAIN (2021-01..2024-07): ratio >= 0.5, сделок >= 30 и история с 2023-01 или раньше
  (меньше полутора лет train — не отбираем). Holdout по монетам не печатается: смотрим его один раз — для группы
  отобранных монет (депозит $1000 на монету) и для портфеля «5 текущих + отобранные».
  Группа проходит, если её holdout ratio >= 0.5, а расширенный портфель на holdout не хуже текущих 5 монет.
"""
import json
import pandas as pd
import hypothesis_runner as hr

NEW = ["BNB", "DOGE", "NEAR", "APT", "ARB", "OP", "SUI", "INJ", "FET", "TIA", "WIF", "1000PEPE"]
PER_COIN = 1000.0
KEEP = ("annual_return_pct", "max_drawdown_pct", "ratio", "worst_month_pct", "trades", "win_rate_pct")


def run(coins):
    p = hr.resolve("alt_short", {})
    p["coins"] = coins
    r = hr.RUNNERS["alt_short"](p, lambda s: None)
    dep = PER_COIN * len(coins)
    return r["equity"] - r["deposit"] + dep, r["trades"], dep


def st(eq, tr, dep, a, b):
    return {k: v for k, v in hr.period_stats(eq, dep, tr, a, b).items() if k in KEEP}


if __name__ == "__main__":
    picked, rows = [], {}
    for c in NEW:
        first = pd.read_csv(hr.csv_path(c), usecols=["timestamp"], nrows=1, parse_dates=["timestamp"]).timestamp[0]
        eq, tr, dep = run([c])
        s = st(eq, tr, dep, max(hr.START, first + pd.Timedelta(days=60)), hr.SPLIT)
        ok = s.get("ratio", -9) >= 0.5 and s.get("trades", 0) >= 30 and first <= pd.Timestamp("2023-01-01")
        rows[c] = {"since": str(first.date()), "train": s, "picked": ok}
        print(c, json.dumps(rows[c]), flush=True)
        if ok:
            picked.append(c)
    out = {"per_coin_train": rows, "picked": picked}
    print("PICKED", picked, flush=True)
    base_eq, base_tr, base_dep = run(hr.ALT_COINS)
    out["current5"] = {p: st(base_eq, base_tr, base_dep, a, b)
                       for p, (a, b) in {"train": (hr.START, hr.SPLIT), "hold": (hr.SPLIT, hr.END)}.items()}
    print("CURRENT5", json.dumps(out["current5"]), flush=True)
    if picked:
        for name, coins in {"picked": picked, "current5+picked": hr.ALT_COINS + picked}.items():
            eq, tr, dep = run(coins)
            out[name] = {p: st(eq, tr, dep, a, b)
                         for p, (a, b) in {"train": (hr.START, hr.SPLIT), "hold": (hr.SPLIT, hr.END)}.items()}
            print(name.upper(), json.dumps(out[name]), flush=True)
    json.dump(out, open("alt_short_new_coins_results.json", "w"), indent=1, default=str)
