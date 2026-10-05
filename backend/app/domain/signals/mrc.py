"""
Mean Reversion Channel (MRC) — перенос services/backtester/indicators.py
(TechnicalIndicators.calculate_mrc / _supersmoother) для live-сигналов.

Формула должна совпадать с бэктестером один в один — это проверяет
tests/test_mrc_signal.py на фикстуре, посчитанной бэктестером.
"""
import numpy as np
import pandas as pd


def supersmoother(src: pd.Series, length: int) -> pd.Series:
    """Ehlers SuperSmoother. out[0] = src[0], out[1] = src[1], дальше рекурсия."""
    a1 = np.exp(-np.sqrt(2) * np.pi / length)
    b1 = 2 * a1 * np.cos(np.sqrt(2) * np.pi / length)
    c3 = -a1 ** 2
    c2 = b1
    c1 = 1 - c2 - c3

    src_vals = src.values
    out = np.empty(len(src_vals), dtype=float)
    for i in range(len(src_vals)):
        if i < 2:
            out[i] = src_vals[i]
        else:
            out[i] = c1 * src_vals[i] + c2 * out[i - 1] + c3 * out[i - 2]
    return pd.Series(out, index=src.index)


def calculate_mrc(df: pd.DataFrame, length: int = 200, inner_mult: float = 1.0,
                  outer_mult: float = 2.415, gradsize: float = 0.5,
                  source: str = "hlc3") -> pd.DataFrame:
    """Колонки: meanline, meanrange, upband1, loband1, upband2, loband2, risk_zone.

    risk_zone: 1..5 выше средней (3 — extreme overbought, 2 — medium, 1 — light,
    4 — около средней, 5 — прочее), зеркально -1..-5 ниже средней, 0 — на средней.
    """
    high, low, close = df["high"], df["low"], df["close"]

    if source == "close":
        src = close
    elif source == "ohlc4":
        src = (df["open"] + high + low + close) / 4
    else:
        src = (high + low + close) / 3

    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    tr.iloc[0] = high.iloc[0] - low.iloc[0]

    meanline = supersmoother(src, length)
    meanrange = supersmoother(tr, length)

    upband1 = meanline + meanrange * np.pi * inner_mult
    loband1 = meanline - meanrange * np.pi * inner_mult
    upband2 = meanline + meanrange * np.pi * outer_mult
    loband2 = meanline - meanrange * np.pi * outer_mult

    step = meanrange * gradsize
    upband2_1 = upband2 + step * 4
    loband2_1 = loband2 - step * 4

    above_mean = close > meanline
    below_mean = close < meanline

    risk_zone_above = np.select(
        [close >= upband2_1, close >= upband2, close > upband2 - step * 8, close <= meanline + meanrange],
        [3, 2, 1, 4], default=5,
    )
    risk_zone_below = np.select(
        [close <= loband2_1, close <= loband2, close < loband2 + step * 8, close >= meanline - meanrange],
        [-3, -2, -1, -4], default=-5,
    )
    risk_zone = pd.Series(
        np.where(above_mean, risk_zone_above, np.where(below_mean, risk_zone_below, 0)),
        index=df.index,
    )

    return pd.DataFrame({
        "meanline": meanline, "meanrange": meanrange,
        "upband1": upband1, "loband1": loband1,
        "upband2": upband2, "loband2": loband2,
        "risk_zone": risk_zone,
    }, index=df.index)
