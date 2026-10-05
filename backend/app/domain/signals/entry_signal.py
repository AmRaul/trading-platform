"""
Сигнал входа «MRC + фильтр тренда» — чистая логика без I/O.

На вход только ЗАКРЫТЫЕ свечи (самая старая первой). Решение принимается по
последней закрытой свече сигнального ТФ и последней закрытой свече трендового ТФ —
так же, как в бэктесте (services/backtester/research/mrc_dca_trend_long.py).
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from app.domain.signals.mrc import calculate_mrc


@dataclass
class EntrySignalResult:
    triggered: bool
    risk_zone: Optional[int] = None
    trend_ok: Optional[bool] = None
    trend_close: Optional[float] = None
    trend_ema: Optional[float] = None
    reason: str = ""


def _frame(candles: List[Dict]) -> pd.DataFrame:
    return pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])


def evaluate_mrc_entry(
    side: str,
    signal_candles: List[Dict],
    trend_candles: Optional[List[Dict]],
    cfg: Dict,
) -> EntrySignalResult:
    length = cfg.get("mrc_length", 200)
    if len(signal_candles) < length:
        return EntrySignalResult(False, reason=f"мало свечей для MRC: {len(signal_candles)} < {length}")

    mrc = calculate_mrc(
        _frame(signal_candles),
        length=length,
        inner_mult=cfg.get("mrc_inner_mult", 1.0),
        outer_mult=cfg.get("mrc_outer_mult", 2.415),
        gradsize=cfg.get("mrc_gradsize", 0.5),
        source=cfg.get("mrc_source", "hlc3"),
    )
    risk_zone = int(mrc["risk_zone"].iloc[-1])
    band = cfg.get("entry_band", 2)
    zone_hit = risk_zone == (-band if side == "LONG" else band)

    trend_ok, trend_close, trend_ema = True, None, None
    ema_period = cfg.get("trend_ema_period")
    if ema_period:
        if not trend_candles or len(trend_candles) < ema_period:
            return EntrySignalResult(False, risk_zone=risk_zone,
                                     reason=f"мало свечей для EMA{ema_period}")
        closes = _frame(trend_candles)["close"]
        trend_ema = float(closes.ewm(span=ema_period, adjust=False).mean().iloc[-1])
        trend_close = float(closes.iloc[-1])
        trend_ok = trend_close > trend_ema if side == "LONG" else trend_close < trend_ema

    triggered = zone_hit and trend_ok
    if triggered:
        reason = "сигнал"
    elif not zone_hit:
        reason = f"risk_zone={risk_zone}"
    else:
        reason = "тренд против направления"
    return EntrySignalResult(triggered, risk_zone, trend_ok, trend_close, trend_ema, reason)


def closed_candles(candles: List[Dict], interval_ms: int, now_ms: int) -> List[Dict]:
    """Сортирует по времени и отбрасывает ещё не закрытую свечу."""
    ordered = sorted(candles, key=lambda c: c["timestamp"])
    return [c for c in ordered if c["timestamp"] + interval_ms <= now_ms]
