"""
Рыночный контекст монеты для разбора (MCP get_market_context): сжатые свечи
и уже посчитанные индикаторы, чтобы модель не выводила их из сырых данных.

Режим — тот же, что у шорт-пирамиды: up — close > EMA200 и EMA50 > EMA200,
down — close < EMA200 и EMA50 < EMA200, иначе mixed.
RSI и ATR — по Уайлдеру (как в TradingView).
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

EMA_PERIODS = (20, 50, 200)
RSI_PERIOD = 14
ATR_PERIOD = 14
BB_PERIOD, BB_MULT = 20, 2.0
VOLUME_AVG = 20


def _r(v, digits: int = 6) -> Optional[float]:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return None
    return float(round(float(v), digits))


def _price_digits(price: float) -> int:
    """Знаков после запятой, чтобы цена читалась: BTC — 1, PEPE — 8."""
    if price <= 0:
        return 8
    return int(max(1, min(8, 4 - np.floor(np.log10(price)))))


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100.0)


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    prev = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _date(ts_ms: int, intraday: bool) -> str:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M" if intraday else "%Y-%m-%d")


def build_market_context(candles: List[Dict], timeframe: str, bars: int = 30) -> Dict:
    """candles — закрытые и незакрытая последняя свеча в любом порядке
    (Bybit отдаёт от новой к старой). bars — сколько последних свечей
    вернуть в ответе; индикаторы считаются по всей истории."""
    if len(candles) < 2:
        return {"error": "Недостаточно свечей"}
    df = pd.DataFrame(candles).sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    close = df["close"]
    last = df.iloc[-1]
    price = float(last["close"])
    pd_digits = _price_digits(price)
    intraday = timeframe not in ("D", "W", "M")

    emas = {p: close.ewm(span=p, adjust=False).mean() for p in EMA_PERIODS}
    atr = _atr(df, ATR_PERIOD)
    rsi = _rsi(close, RSI_PERIOD)
    mid = close.rolling(BB_PERIOD).mean()
    std = close.rolling(BB_PERIOD).std(ddof=0)
    upper, lower = mid + BB_MULT * std, mid - BB_MULT * std
    atr_now = float(atr.iloc[-1])

    ema_info = {}
    for p, s in emas.items():
        v = float(s.iloc[-1])
        ema_info[f"ema{p}"] = {
            "value": _r(v, pd_digits),
            "distance_pct": _r((price / v - 1) * 100, 2),
            "distance_atr": _r((price - v) / atr_now, 2) if atr_now else None,
            "reliable": len(df) >= p * 2,  # EMA до ~2 периодов истории ещё «разгоняется»
        }

    e50, e200 = float(emas[50].iloc[-1]), float(emas[200].iloc[-1])
    if price > e200 and e50 > e200:
        regime = "up"
    elif price < e200 and e50 < e200:
        regime = "down"
    else:
        regime = "mixed"

    window = df.tail(bars)
    hi_idx, lo_idx = window["high"].idxmax(), window["low"].idxmin()
    # Объём — по последней ЗАКРЫТОЙ свече: у текущей он неполный и всегда «низкий»
    vol_avg = float(df["volume"].iloc[-VOLUME_AVG - 2:-2].mean()) if len(df) > VOLUME_AVG + 1 else None
    last_closed_volume = float(df["volume"].iloc[-2])
    bb_width = float(upper.iloc[-1] - lower.iloc[-1]) if np.isfinite(upper.iloc[-1]) else None

    return {
        "timeframe": timeframe,
        "price": _r(price, pd_digits),
        "as_of": _date(int(last["timestamp"]), True),
        "last_candle_closed": False,  # последняя свеча Bybit — текущая, ещё не закрыта
        "change_over_window_pct": _r((price / float(window["close"].iloc[0]) - 1) * 100, 2),
        "regime": regime,
        "regime_rule": "up: close>EMA200 и EMA50>EMA200; down: close<EMA200 и EMA50<EMA200",
        **ema_info,
        "rsi14": _r(float(rsi.iloc[-1]), 1),
        "atr14": _r(atr_now, pd_digits),
        "atr14_pct": _r(atr_now / price * 100, 2),
        "bollinger20": {
            "upper": _r(float(upper.iloc[-1]), pd_digits),
            "lower": _r(float(lower.iloc[-1]), pd_digits),
            "percent_b": _r((price - float(lower.iloc[-1])) / bb_width, 2) if bb_width else None,
            "width_pct": _r(bb_width / price * 100, 2) if bb_width else None,
        },
        "window_extremes": {
            "bars": len(window),
            "high": _r(float(df.at[hi_idx, "high"]), pd_digits),
            "high_at": _date(int(df.at[hi_idx, "timestamp"]), intraday),
            "high_distance_atr": _r((float(df.at[hi_idx, "high"]) - price) / atr_now, 2) if atr_now else None,
            "low": _r(float(df.at[lo_idx, "low"]), pd_digits),
            "low_at": _date(int(df.at[lo_idx, "timestamp"]), intraday),
            "low_distance_atr": _r((price - float(df.at[lo_idx, "low"])) / atr_now, 2) if atr_now else None,
        },
        "last_closed_volume_vs_avg20": _r(last_closed_volume / vol_avg, 2) if vol_avg else None,
        "history_bars": len(df),
        "candles": {
            "columns": ["time", "open", "high", "low", "close", "volume"],
            "rows": [
                [_date(int(r.timestamp), intraday), _r(r.open, pd_digits), _r(r.high, pd_digits),
                 _r(r.low, pd_digits), _r(r.close, pd_digits), _r(r.volume, 2)]
                for r in window.itertuples()
            ],
        },
    }
