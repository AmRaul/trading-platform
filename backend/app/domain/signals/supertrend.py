"""
Supertrend — перенос supertrend_dir из services/backtester/research/mrc_supertrend_pyramid.py
для live-сигналов.

Формула должна совпадать с исследованием один в один — иначе живой бот входит
не там, где входил бэктест стратегии.
"""
import numpy as np
import pandas as pd


def supertrend_direction(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> np.ndarray:
    """Направление тренда по барам: 1 — вверх, −1 — вниз, 0 — прогрев (первые period×3 баров).
    ATR — EMA истинного диапазона с alpha = 1/period (как ta.atr в Pine)."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(abs(h - prev_c), abs(l - prev_c)))
    atr = pd.Series(tr).ewm(alpha=1 / period, adjust=False).mean().values
    hl2 = (h + l) / 2
    up, dn = hl2 - mult * atr, hl2 + mult * atr
    fu, fd = up.copy(), dn.copy()
    trend = np.ones(len(c), dtype=int)
    for i in range(1, len(c)):
        fu[i] = max(up[i], fu[i - 1]) if c[i - 1] > fu[i - 1] else up[i]
        fd[i] = min(dn[i], fd[i - 1]) if c[i - 1] < fd[i - 1] else dn[i]
        if trend[i - 1] == -1 and c[i] > fd[i - 1]:
            trend[i] = 1
        elif trend[i - 1] == 1 and c[i] < fu[i - 1]:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]
    trend[:period * 3] = 0
    return trend
