"""
Сигналы входа — чистая логика без I/O:
  - «MRC + фильтр тренда» (services/backtester/research/mrc_dca_trend_long.py);
  - «разворот Supertrend + режим тренда» (services/backtester/research/trend_pullback_pyramid.py).

На вход только ЗАКРЫТЫЕ свечи (самая старая первой). Решение принимается по
последней закрытой свече сигнального ТФ и последней закрытой свече трендового ТФ —
так же, как в бэктесте.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from app.domain.signals.mrc import calculate_mrc
from app.domain.signals.supertrend import supertrend_direction


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


def _trend_filter(side: str, trend_candles: Optional[List[Dict]], cfg: Dict):
    """Фильтр тренда по последней закрытой свече трендового ТФ.
    LONG: close > EMA(trend_ema_period) и, если задан trend_ema_fast, EMA fast > EMA slow;
    SHORT — зеркально. Без trend_ema_period фильтр выключен.
    Возвращает (trend_ok, close, ema) или строку-причину, если свечей мало."""
    ema_period = cfg.get("trend_ema_period")
    if not ema_period:
        return True, None, None
    if not trend_candles or len(trend_candles) < ema_period:
        return f"мало свечей для EMA{ema_period}"
    closes = _frame(trend_candles)["close"]
    ema = float(closes.ewm(span=ema_period, adjust=False).mean().iloc[-1])
    close = float(closes.iloc[-1])
    ok = close > ema if side == "LONG" else close < ema
    fast_period = cfg.get("trend_ema_fast")
    if fast_period:
        fast = float(closes.ewm(span=fast_period, adjust=False).mean().iloc[-1])
        ok = ok and (fast > ema if side == "LONG" else fast < ema)
    return ok, close, ema


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

    trend = _trend_filter(side, trend_candles, cfg)
    if isinstance(trend, str):
        return EntrySignalResult(False, risk_zone=risk_zone, reason=trend)
    trend_ok, trend_close, trend_ema = trend

    triggered = zone_hit and trend_ok
    if triggered:
        reason = "сигнал"
    elif not zone_hit:
        reason = f"risk_zone={risk_zone}"
    else:
        reason = "тренд против направления"
    return EntrySignalResult(triggered, risk_zone, trend_ok, trend_close, trend_ema, reason)


def evaluate_supertrend_entry(
    side: str,
    signal_candles: List[Dict],
    trend_candles: Optional[List[Dict]],
    cfg: Dict,
) -> EntrySignalResult:
    """Сигнал — Supertrend сигнального ТФ развернулся в сторону сделки ровно
    на последней закрытой свече, и тренд старшего ТФ в ту же сторону."""
    period = cfg.get("st_period", 10)
    if len(signal_candles) < period * 3 + 2:
        return EntrySignalResult(False, reason=f"мало свечей для Supertrend: {len(signal_candles)}")

    direction = supertrend_direction(_frame(signal_candles), period, cfg.get("st_mult", 3.0))
    want = 1 if side == "LONG" else -1
    flipped = direction[-1] == want and direction[-2] == -want

    trend = _trend_filter(side, trend_candles, cfg)
    if isinstance(trend, str):
        return EntrySignalResult(False, reason=trend)
    trend_ok, trend_close, trend_ema = trend

    triggered = flipped and trend_ok
    if triggered:
        reason = "сигнал"
    elif not flipped:
        reason = f"supertrend={int(direction[-1])}, разворота нет"
    else:
        reason = "тренд против направления"
    return EntrySignalResult(triggered, None, trend_ok, trend_close, trend_ema, reason)


EVALUATORS = {"mrc": evaluate_mrc_entry, "supertrend": evaluate_supertrend_entry}


def evaluate_entry(side: str, signal_candles: List[Dict], trend_candles: Optional[List[Dict]],
                   cfg: Dict) -> EntrySignalResult:
    return EVALUATORS[cfg.get("type", "mrc")](side, signal_candles, trend_candles, cfg)


def closed_candles(candles: List[Dict], interval_ms: int, now_ms: int) -> List[Dict]:
    """Сортирует по времени и отбрасывает ещё не закрытую свечу."""
    ordered = sorted(candles, key=lambda c: c["timestamp"])
    return [c for c in ordered if c["timestamp"] + interval_ms <= now_ms]
