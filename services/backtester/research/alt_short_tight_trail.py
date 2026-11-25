"""Консервативный шорт альтов: после заполнения всей сетки (4-й ордер) трейлинг ближе — X×U вместо 1U.

Записано ДО прогона (2026-11-25):
  варианты X = 0.3, 0.5, 0.7 (U — медианный дневной диапазон монеты, как у trailing_u);
  лучший выбирается ТОЛЬКО по train (2021-01..2024-07) и должен поднять train ratio минимум на 0.1 к базе;
  holdout открывается один раз — только для выбранного, проходит если holdout ratio >= базы.
"""
import json
import pandas as pd
import hypothesis_runner as hr
import short_portfolio as sp
import mrc_supertrend_pyramid as msp, trend_pullback_pyramid as tpp
import donchian_pyramid as dp
from app.domain.trading.position_calculator import PositionCalculator


class FullGridTrail(PositionCalculator):
    """Как в живом боте, но при полной сетке trailing_percent заменяется на trailing_percent_full."""

    def calculate_stop_loss(self, side, orders, current_price, trailing_enabled=True):
        full = self.config.get("trailing_percent_full")
        if full and len(orders) >= self.config["order_count"]:
            saved = self.config["trailing_percent"]
            self.config["trailing_percent"] = full
            try:
                return super().calculate_stop_loss(side, orders, current_price, trailing_enabled)
            finally:
                self.config["trailing_percent"] = saved
        return super().calculate_stop_loss(side, orders, current_price, trailing_enabled)


def run(x):
    p = hr.resolve("alt_short", {})
    dp.DEPOSIT = hr.deposit_of("alt_short", p)
    sp.ENTRY = p["first_order"]

    def cfg(df, step):
        c = dp.bot_config(0, p["order_count"], False, None)
        u = dp.vol_unit(df)
        c.update(entry_size_usdt=p["first_order"], tp_percent=p["tp_percent"], step_percent=p["step_percent"],
                 sl_initial=p["sl_percent"], sl_after_order3=p["sl_percent"],
                 trailing_percent=round(u * p["trailing_u"], 1),
                 trailing_percent_full=round(u * x, 1) if x else None)
        return c

    by_coin = {c: hr.alt_coin_trades(c, p, cfg, "SHORT") for c in p["coins"]}
    pnl, taken, _ = sp.portfolio(by_coin, len(p["coins"]), "first")
    dep = dp.DEPOSIT
    eq = pd.Series(dep + pnl, index=sp.GRID_IDX)
    idx = sp.GRID_IDX
    tr = pd.DataFrame([{"exit": idx[t[1]], "pnl": t[2], "orders": t[3]} for _, t in taken])
    return eq, tr, dep, p["order_count"]


if __name__ == "__main__":
    load = lambda c: (pd.read_csv(hr.csv_path(c), parse_dates=["timestamp"])  # noqa: E731
                      .sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True))
    msp.load_15m = sp.load_15m = tpp.load_15m = load
    sp.PositionCalculator = FullGridTrail
    res, runs = {}, {}
    for x in (None, 0.3, 0.5, 0.7):
        runs[x] = run(x)
        eq, tr, dep, oc = runs[x]
        res[str(x)] = {"train": hr.period_stats(eq, dep, tr, hr.START, hr.SPLIT, oc)}
        print("X", x, json.dumps(res[str(x)]), flush=True)
    base = res["None"]["train"]["ratio"]
    best = max((0.3, 0.5, 0.7), key=lambda x: res[str(x)]["train"]["ratio"])
    gain = res[str(best)]["train"]["ratio"] - base
    out = {"train": res, "best": best, "train_gain": round(gain, 2)}
    if gain >= 0.1:
        for x in (None, best):
            eq, tr, dep, oc = runs[x]
            out.setdefault("holdout", {})[str(x)] = hr.period_stats(eq, dep, tr, hr.SPLIT, hr.END, oc)
        out["passed"] = out["holdout"][str(best)]["ratio"] >= out["holdout"]["None"]["ratio"]
    else:
        out["passed"] = False
        out["note"] = "на train прирост < 0.1 — holdout не открываем"
    print(json.dumps({k: v for k, v in out.items() if k != "train"}, indent=1), flush=True)
    json.dump(out, open("alt_short_tight_trail_results.json", "w"), indent=1)
