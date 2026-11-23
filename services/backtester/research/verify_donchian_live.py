"""Сверка живого сигнала Donchian (backend/app/domain/signals/entry_signal.py) с исследованием
(long_trend_classic.signals V2) на тех же свечах: для случайных часов строим закрытые 1h и дневки
так, как их видит планировщик, и сравниваем вход и выход.

Запуск (из services/backtester, PYTHONPATH=.:research:../../backend):
    python research/verify_donchian_live.py
"""
import numpy as np
import pandas as pd

import long_trend_classic as lt
from app.domain.signals.entry_signal import evaluate_donchian_entry, evaluate_donchian_exit

CFG = {"type": "donchian", "timeframe": "60", "donchian_entry_days": 20, "donchian_exit_days": 10}
rng = np.random.default_rng(0)
total = bad = 0
for coin in lt.COINS:
    h1 = lt.load(coin)
    entry, exit_, _ = lt.signals(h1, "V2_donch20_10")
    d = lt.ohlc(h1.reset_index(), "1D")
    d_rows = [{"timestamp": int(t.value // 10**6), "open": r.open, "high": r.high, "low": r.low, "close": r.close}
              for t, r in d.iterrows()]
    d_ts = np.array([r["timestamp"] for r in d_rows])
    for i in rng.choice(np.arange(24 * 40, len(h1)), 1500, replace=False):
        bar_close_ms = int((h1.index[i] + pd.Timedelta("1h")).value // 10**6)
        closed_days = [d_rows[k] for k in np.where(d_ts + 86_400_000 <= bar_close_ms)[0][-60:]]
        sig = [{"close": float(h1["close"].iloc[i])}]
        e = evaluate_donchian_entry("LONG", sig, closed_days, CFG).triggered
        x = evaluate_donchian_exit("LONG", sig, closed_days, CFG).triggered
        total += 1
        if e != bool(entry[i]) or x != bool(exit_[i]):
            bad += 1
print(f"проверено {total} часов, расхождений: {bad}")
