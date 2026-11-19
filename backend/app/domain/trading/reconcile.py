"""
Сверка живой/бумажной позиции с повтором на свечах (replay_position).

Вердикт:
  match        — те же доборы и тот же выход, цены и время в пределах допуска;
  price_drift  — механика та же (число ордеров, причина выхода), но цены/время дальше допуска
                 (проскальзывание, тики против OHLC) — не поломка, но смотреть на величину;
  mismatch     — другое число ордеров или другой выход: бот и бэктест разошлись;
  manual       — позицию закрыли руками, выход не сравнивается.
"""
from typing import Dict, List, Optional

from app.domain.trading.replay import ReplayResult

PRICE_TOL_PCT = 0.15
TIME_TOL_MS = 5 * 60_000


def _pct(a: float, b: float) -> float:
    return round((a / b - 1) * 100, 3) if b else 0.0


def compare_with_replay(
    live_orders: List[Dict],
    live_exit: Optional[Dict],
    replay: ReplayResult,
    price_tol_pct: float = PRICE_TOL_PCT,
    time_tol_ms: int = TIME_TOL_MS,
) -> Dict:
    """live_orders: [{number, time_ms, price}] по возрастанию номера;
    live_exit: {time_ms, price, reason} или None, если позиция открыта."""
    issues: List[str] = []
    drift: List[str] = []

    orders = []
    for i in range(max(len(live_orders), len(replay.orders))):
        lo = live_orders[i] if i < len(live_orders) else None
        ro = replay.orders[i] if i < len(replay.orders) else None
        row = {"number": i + 1,
               "live_price": lo and lo["price"], "replay_price": ro and round(ro.price, 8),
               "live_time_ms": lo and lo["time_ms"], "replay_time_ms": ro and ro.time_ms}
        if lo and ro:
            row["price_diff_pct"] = _pct(lo["price"], ro.price)
            row["time_diff_min"] = round((lo["time_ms"] - ro.time_ms) / 60_000, 1)
            if i > 0 and (abs(row["price_diff_pct"]) > price_tol_pct or abs(lo["time_ms"] - ro.time_ms) > time_tol_ms):
                drift.append(f"ордер {i + 1}: цена {row['price_diff_pct']:+.3f}%, время {row['time_diff_min']:+.1f} мин")
        orders.append(row)

    manual = bool(live_exit and live_exit["reason"] not in ("SL_HIT", "TRAILING_STOP", "TP_HIT"))
    if manual:
        # После ручного закрытия сравниваем только доборы, сделанные до него
        replay_before = [o for o in replay.orders if o.time_ms <= live_exit["time_ms"]]
        if len(replay_before) != len(live_orders):
            issues.append(f"доборов до ручного закрытия: бот {len(live_orders)}, бэктест {len(replay_before)}")
    elif len(live_orders) != len(replay.orders):
        issues.append(f"ордеров: бот {len(live_orders)}, бэктест {len(replay.orders)}")

    exit_cmp = None
    if not manual:
        if live_exit is None and not replay.is_open:
            issues.append(f"бот держит позицию, а бэктест закрыл бы её ({replay.exit_reason} по {replay.exit_price:.6g})")
        elif live_exit is not None and replay.is_open:
            issues.append(f"бот закрыл позицию ({live_exit['reason']}), а бэктест держал бы её дальше")
        elif live_exit is not None:
            exit_cmp = {
                "live_reason": live_exit["reason"], "replay_reason": replay.exit_reason,
                "live_price": live_exit["price"], "replay_price": round(replay.exit_price, 8),
                "price_diff_pct": _pct(live_exit["price"], replay.exit_price),
                "time_diff_min": round((live_exit["time_ms"] - replay.exit_time_ms) / 60_000, 1),
            }
            if live_exit["reason"] != replay.exit_reason:
                issues.append(f"выход: бот {live_exit['reason']}, бэктест {replay.exit_reason}")
            elif (abs(exit_cmp["price_diff_pct"]) > price_tol_pct
                  or abs(live_exit["time_ms"] - replay.exit_time_ms) > time_tol_ms):
                drift.append(f"выход: цена {exit_cmp['price_diff_pct']:+.3f}%, время {exit_cmp['time_diff_min']:+.1f} мин")

    verdict = "manual" if manual and not issues else "mismatch" if issues else "price_drift" if drift else "match"
    return {
        "verdict": verdict,
        "issues": issues,
        "drift": drift,
        "orders": orders,
        "exit": exit_cmp,
        "replay_open": replay.is_open,
        "replay_current_sl": replay.current_sl,
        "tolerance": {"price_pct": price_tol_pct, "time_min": time_tol_ms // 60_000},
    }
