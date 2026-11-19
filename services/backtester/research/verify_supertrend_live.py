"""
Сверка live-сигнала (backend evaluate_supertrend_entry по окну 1000 закрытых
свечей, как берёт CheckEntrySignalUseCase) с сигналом исследования
trend_pullback_pyramid (полная история).

Проверяются все бары с сигналом исследования и случайные бары без сигнала.

Запуск (backend и research в PYTHONPATH):
    python research/verify_supertrend_live.py SOL AVAX LINK ETH XRP
"""
import sys

import numpy as np
import pandas as pd

import trend_pullback_pyramid as tpp
from mrc_supertrend_pyramid import load_15m, resample
from app.domain.signals.entry_signal import evaluate_supertrend_entry

WINDOW = 1000
RANDOM_BARS = 1500
CFG = {"type": "supertrend", "timeframe": "15", "st_period": 10, "st_mult": 3.0,
       "trend_ema_period": 200, "trend_ema_fast": 50, "trend_timeframe": "240"}


def records(x):
    return x[["timestamp", "open", "high", "low", "close", "volume"]].to_dict("records")


def check(coin, rng):
    df = load_15m(coin)
    h4 = df.resample("4h", on="timestamp").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index()
    h4_close = (h4["timestamp"] + pd.Timedelta("4h")).values
    bar_close = (df["timestamp"] + pd.Timedelta("15min")).values

    up, dn = tpp.regime(df)
    st_up, st_dn = tpp.triggers(df)["st"]
    research = {"LONG": up & st_up, "SHORT": dn & st_dn}

    # нужна 1000 закрытых 4h-свечей → начинаем после них
    first = int(np.searchsorted(bar_close, h4_close[WINDOW - 1]))
    out = {}
    for side, sig in research.items():
        hits = np.where(sig[first:])[0] + first
        pool = np.setdiff1d(np.arange(first, len(df)), hits)
        sample = np.concatenate([hits, rng.choice(pool, min(RANDOM_BARS, len(pool)), replace=False)])
        mism = []
        for i in sample:
            sc = records(df.iloc[i - WINDOW + 1:i + 1])
            n4 = int(np.searchsorted(h4_close, bar_close[i], side="right"))
            tc = records(h4.iloc[n4 - WINDOW:n4])
            live = evaluate_supertrend_entry(side, sc, tc, CFG).triggered
            if live != bool(sig[i]):
                mism.append((str(df["timestamp"].iloc[i]), bool(sig[i]), live))
        out[side] = (len(hits), len(sample), mism)
    return out


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    total_bad = 0
    for coin in sys.argv[1:]:
        for side, (n_hits, n, mism) in check(coin, rng).items():
            total_bad += len(mism)
            print(f"{coin:5s} {side:5s} сигналов {n_hits:4d}, проверено баров {n:5d}, расхождений {len(mism)}"
                  + (f" — {mism[:3]}" if mism else ""))
    sys.exit(1 if total_bad else 0)
