"""Классические лонг-трендовые системы на 1h-сетке. Вход/выход по сигналу закрытого бара — по open следующего.
Позиция $1000 на монету (1:1), комиссия 0.055% за сторону, funding 0.01%/8ч с лонга, проскальзывание стопа 0.05%."""
import json
import sys
import numpy as np, pandas as pd
import hypothesis_runner as hr
from mrc_supertrend_pyramid import supertrend_dir

FEE, SLIP, FUND_1H, SIZE = 0.00055, 0.0005, 0.0001 / 8, 1000.0
COINS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "XRP"]

def ohlc(df, tf):
    return df.resample(tf, on="timestamp").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()

def to_1h(series, tf, h1):
    """Значение старшего бара доступно после его закрытия."""
    s = pd.DataFrame({"t": series.index + pd.Timedelta(tf), "v": series.values})
    bars = pd.DataFrame({"t": h1.index + pd.Timedelta("1h")})
    return pd.merge_asof(bars, s, on="t")["v"].values

def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def signals(h1, variant):
    c = h1["close"]
    if variant == "V1_regime4h":
        x = ohlc(h1.reset_index(), "4h")
        up = ((x.close > ema(x.close, 200)) & (ema(x.close, 50) > ema(x.close, 200))).astype(float)
        up.iloc[:200] = 0
        u = to_1h(up, "4h", h1) == 1
        return u, ~u, None
    if variant in ("V2_donch20_10", "V3_donch55_atr3"):
        d = ohlc(h1.reset_index(), "1D")
        n_in = 20 if variant == "V2_donch20_10" else 55
        hi = to_1h(d.high.rolling(n_in).max(), "1D", h1)
        entry = c.values > hi
        if variant == "V2_donch20_10":
            lo = to_1h(d.low.rolling(10).min(), "1D", h1)
            return entry, c.values < lo, None
        tr = np.maximum(d.high - d.low, np.maximum(abs(d.high - d.close.shift()), abs(d.low - d.close.shift())))
        atr = to_1h(tr.rolling(20).mean(), "1D", h1)
        return entry, np.zeros(len(h1), bool), 3 * atr
    if variant == "V4_st1h_regime4h":
        x = ohlc(h1.reset_index(), "4h")
        up = ((x.close > ema(x.close, 200)) & (ema(x.close, 50) > ema(x.close, 200))).astype(float)
        up.iloc[:200] = 0
        reg = to_1h(up, "4h", h1) == 1
        st = supertrend_dir(h1) == 1
        return reg & st, ~st, None
    raise ValueError(variant)

def simulate(h1, entry, exit_, trail):
    o, h, l, c = (h1[k].values for k in ("open", "high", "low", "close"))
    n = len(h1); eq = np.zeros(n); trades = []
    cash, pos, ep, stop, t_in = 0.0, False, 0.0, 0.0, None
    for i in range(1, n):
        if not pos and entry[i - 1] and not np.isnan(c[i - 1]):
            pos, ep, t_in = True, o[i], h1.index[i]
            cash -= SIZE * FEE
            stop = (c[i - 1] - trail[i - 1]) if trail is not None and not np.isnan(trail[i - 1]) else 0.0
        if pos:
            px = None
            if exit_[i - 1]:
                px = o[i]
            elif stop and l[i] <= stop:
                px = min(o[i], stop) * (1 - SLIP)
            cash -= SIZE * (c[i] / ep if px is None else 1) * FUND_1H
            if px is not None:
                pnl = SIZE * (px - ep) / ep - SIZE * (px / ep) * FEE
                cash += pnl
                trades.append({"entry": t_in, "exit": h1.index[i], "pnl": pnl - SIZE * FEE, "orders": 1})
                pos = False
            elif trail is not None and not np.isnan(trail[i]):
                stop = max(stop, c[i] - trail[i])
        eq[i] = cash + (SIZE * (c[i] - ep) / ep if pos else 0.0)
    return pd.Series(eq, index=h1.index + pd.Timedelta("1h")), pd.DataFrame(trades)

def load(coin):
    df = pd.read_csv(hr.csv_path(coin), parse_dates=["timestamp"]).sort_values("timestamp").drop_duplicates("timestamp")
    h1 = ohlc(df, "1h")
    return h1[(h1.index >= hr.START - pd.Timedelta(days=120)) & (h1.index < hr.END)]

if __name__ == "__main__":
    data = {c: load(c) for c in COINS}
    res = {}
    for v in ["V1_regime4h", "V2_donch20_10", "V3_donch55_atr3", "V4_st1h_regime4h"]:
        eqs, trs = [], []
        per = {}
        for coin, h1 in data.items():
            e, x, t = signals(h1, v)
            eq, tr = simulate(h1, np.nan_to_num(e, nan=0).astype(bool), np.nan_to_num(x, nan=0).astype(bool), t)
            eq = eq[eq.index >= hr.START]
            eqs.append(eq); trs.append(tr)
            per[coin] = {p: hr.period_stats(1000 + eq, 1000, tr, a, b)["ratio"] for p, (a, b) in
                         {"train": (hr.START, hr.SPLIT), "hold": (hr.SPLIT, hr.END)}.items()}
        idx = eqs[0].index
        for e in eqs[1:]: idx = idx.union(e.index)
        tot = sum(e.reindex(idx).ffill().fillna(0) for e in eqs)
        dep = 1000.0 * len(COINS)
        trades = pd.concat([t for t in trs if len(t)], ignore_index=True)
        r = {"train": hr.period_stats(dep + tot, dep, trades, hr.START, hr.SPLIT),
             "hold": hr.period_stats(dep + tot, dep, trades, hr.SPLIT, hr.END), "per_coin_ratio": per}
        res[v] = r
        print(v, json.dumps(r), flush=True)
    json.dump(res, open("long_trend_classic_results.json", "w"), indent=1)
