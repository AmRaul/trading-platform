"""Поиск ног, не похожих на текущий портфель (шорт альтов + Donchian 20/10 лонг).

Критерии записаны ДО прогона (2026-11-25):
  1) ratio (годовая доходность / макс. просадка от депозита) >= 0.5 и на train (2021-01..2024-07), и на holdout;
  2) корреляция месячного PnL с текущим портфелем <= 0.3 (на train);
  3) портфель + идея (равный депозит) — ratio на holdout выше, чем у портфеля без неё.

Идеи:
  XS_MOM  — раз в неделю (пн 00:00 UTC): лонг 3 лучших по доходности за 28 дней, шорт 3 худших; $1000 на слот.
  XS_REV  — каждый день: лонг 3 худших за последние сутки, шорт 3 лучших; $1000 на слот.
  DON_SHORT — Donchian 20/10 в шорт на 6 монетах (вход close 1h < min low 20 дневок, выход > max high 10).
Ранжирование по close дня t-1, позиция держится с close t: сигнал не видит цену входа.
Комиссия 0.055% + проскальзывание 0.05% на каждый оборот. Funding в XS не учитывается (лонг и шорт
поровну), у DON_SHORT шорт funding не получает (консервативно).
Оговорка: вселенная — монеты, живые сегодня (выжившие), это завышает лонг-сторону импульса.
"""
import json
import numpy as np, pandas as pd
import hypothesis_runner as hr
import long_trend_classic as ltc

UNIVERSE = ["BTC", "ETH", "SOL", "AVAX", "LINK", "XRP", "BNB", "DOGE", "NEAR", "APT", "ARB", "OP",
            "SUI", "INJ", "FET", "TIA", "WIF", "1000PEPE"]
SLOT, K, COST = 1000.0, 3, 0.00055 + 0.0005
DEP_XS = SLOT * 2 * K


def daily_closes():
    out = {}
    for c in UNIVERSE:
        p = hr.DATA / f"{c}USDT_15m_binance_futures.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p, usecols=["timestamp", "close"], parse_dates=["timestamp"])
        out[c] = df.drop_duplicates("timestamp").set_index("timestamp")["close"].resample("1D").last()
    return pd.DataFrame(out).sort_index()


def xs(close: pd.DataFrame, lookback: int, every: int, reverse: bool):
    """PnL по дням. Монета в выборке, если у неё есть 60 дней истории."""
    ret = close.pct_change(fill_method=None)
    score = close / close.shift(lookback) - 1
    alive = close.notna().rolling(60).sum() >= 60
    w = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    cur = pd.Series(0.0, index=close.columns)
    for i, t in enumerate(close.index):
        if i < 1:
            continue
        if i % every == 0:
            s = score.iloc[i - 1][alive.iloc[i - 1]].dropna()
            cur = pd.Series(0.0, index=close.columns)
            if len(s) >= 2 * K:
                s = s.sort_values()
                lo, hi = s.index[:K], s.index[-K:]
                cur[hi], cur[lo] = (-1, 1) if reverse else (1, -1)
        w.loc[t] = cur
    # w[t] — позиция, взятая на close t; доход — от close t до close t+1
    gross = (w.shift(1) * ret).sum(axis=1) * SLOT
    turnover = w.diff().abs().sum(axis=1) * SLOT
    pnl = gross - turnover * COST
    return pnl, int((w.diff().abs() > 0).sum().sum())


def to_equity(pnl_daily, dep):
    eq = dep + pnl_daily.cumsum()
    return eq[(eq.index >= hr.START) & (eq.index < hr.END)]


def stats(eq, dep, ntr):
    tr = pd.DataFrame({"exit": [hr.START], "pnl": [0.0]})
    return {p: {k: v for k, v in hr.period_stats(eq, dep, tr, a, b).items()
                if k in ("annual_return_pct", "max_drawdown_pct", "ratio", "months_positive_pct", "worst_month_pct")}
            for p, (a, b) in {"train": (hr.START, hr.SPLIT), "hold": (hr.SPLIT, hr.END)}.items()}


def donchian_short():
    eqs, trs = [], []
    for coin in ltc.COINS:
        h1 = ltc.load(coin)
        d = ltc.ohlc(h1.reset_index(), "1D")
        lo = ltc.to_1h(d.low.rolling(20).min(), "1D", h1)
        hi = ltc.to_1h(d.high.rolling(10).max(), "1D", h1)
        c = h1["close"].values
        # зеркало: шорт = лонг по перевёрнутой цене 1/x даёт неверный PnL, считаем прямо
        inv = h1.copy()
        entry, exit_ = np.nan_to_num(c < lo).astype(bool), np.nan_to_num(c > hi).astype(bool)
        eq, tr = simulate_short(inv, entry, exit_)
        eqs.append(eq); trs.append(tr)
    idx = eqs[0].index
    for e in eqs[1:]:
        idx = idx.union(e.index)
    tot = sum(e.reindex(idx).ffill().fillna(0) for e in eqs)
    return tot, sum(len(t) for t in trs)


def simulate_short(h1, entry, exit_):
    o, c = h1["open"].values, h1["close"].values
    n, eq = len(h1), np.zeros(len(h1))
    cash, pos, ep, ntr = 0.0, False, 0.0, 0
    for i in range(1, n):
        if not pos and entry[i - 1]:
            pos, ep = True, o[i]
            cash -= ltc.SIZE * ltc.FEE
        if pos and exit_[i - 1]:
            cash += ltc.SIZE * (ep - o[i]) / ep - ltc.SIZE * (o[i] / ep) * ltc.FEE
            pos, ntr = False, ntr + 1
        eq[i] = cash + (ltc.SIZE * (ep - c[i]) / ep if pos else 0.0)
    return pd.Series(eq, index=h1.index + pd.Timedelta("1h")), [0] * ntr


def monthly(eq):
    return eq.resample("ME").last().diff().dropna()


def current_portfolio():
    """Шорт альтов (база alt_short, $5000) + Donchian 20/10 лонг (6 × $1000), как в комбо 23.11."""
    r = hr.RUNNERS["alt_short"](hr.resolve("alt_short", {}), lambda s: None)
    short_eq = r["equity"] - r["deposit"]
    eqs = []
    for coin in ltc.COINS:
        h1 = ltc.load(coin)
        e, x, t = ltc.signals(h1, "V2_donch20_10")
        eq, _ = ltc.simulate(h1, np.nan_to_num(e, nan=0).astype(bool), np.nan_to_num(x, nan=0).astype(bool), t)
        eqs.append(eq)
    idx = short_eq.index
    for e in eqs:
        idx = idx.union(e.index)
    don = sum(e.reindex(idx).ffill().fillna(0) for e in eqs)
    tot = short_eq.reindex(idx).ffill().fillna(0) + don
    return tot, r["deposit"] + 6000.0


if __name__ == "__main__":
    res = {}
    port, port_dep = current_portfolio()
    port = port[(port.index >= hr.START) & (port.index < hr.END)]
    res["PORTFOLIO"] = stats(port_dep + port, port_dep, 0)
    print("PORTFOLIO", json.dumps(res["PORTFOLIO"]), flush=True)
    pm = monthly(port)

    close = daily_closes()
    ideas = {}
    pnl, n = xs(close, 28, 7, reverse=False); ideas["XS_MOM"] = (pnl.cumsum(), DEP_XS, n)
    pnl, n = xs(close, 1, 1, reverse=True); ideas["XS_REV"] = (pnl.cumsum(), DEP_XS, n)
    tot, n = donchian_short(); ideas["DON_SHORT"] = (tot, 6000.0, n)

    for name, (cum, dep, n) in ideas.items():
        cum = cum[(cum.index >= hr.START) & (cum.index < hr.END)]
        r = stats(dep + cum, dep, n)
        im = monthly(cum)
        j = pd.concat([pm, im], axis=1, join="inner").dropna()
        train = j[j.index < hr.SPLIT]
        r["corr_train"] = round(float(train.iloc[:, 0].corr(train.iloc[:, 1])), 2)
        r["corr_hold"] = round(float(j[j.index >= hr.SPLIT].iloc[:, 0].corr(j[j.index >= hr.SPLIT].iloc[:, 1])), 2)
        idx = port.index.union(cum.index)
        both = port.reindex(idx).ffill().fillna(0) + cum.reindex(idx).ffill().fillna(0)
        r["combo"] = stats(port_dep + dep + both, port_dep + dep, 0)
        r["position_changes"] = n
        res[name] = r
        print(name, json.dumps(r), flush=True)
    json.dump(res, open("new_ideas_results.json", "w"), indent=1)
