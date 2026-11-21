"""Уровни открытой позиции, посчитанные тем же PositionCalculator, что ведёт бота:
стоп и результат сделки на нём с комиссией, тейк, с какой цены трейлинг начнёт
двигать стоп, следующий ордер и каким станет стоп после него.

Раньше это считали вручную в чате (MCP get_position_context отдавал только расстояния).
"""
from typing import Dict, List, Optional

from app.domain.trading.entities import OrderInfo
from app.domain.trading.position_calculator import PositionCalculator

# Оценка комиссии для реальных бирж (taker Bybit 0.055%); paper вычитает ровно её же
DEFAULT_FEE_RATE = 0.00055


def _pct(level: float, price: float) -> float:
    return round((level / price - 1) * 100, 3)


def _net(calc: PositionCalculator, side: str, avg: float, exit_price: float, size: float, fee_rate: float) -> Dict:
    """Результат сделки при выходе по exit_price: как в ClosePositionUseCase (вход+доборы
    и выход по taker на total_size)."""
    gross = calc.calculate_unrealized_pnl(side, avg, exit_price, size)
    fees = fee_rate * size * (1 + exit_price / avg)
    return {"gross_usdt": round(gross, 2), "fees_usdt": round(fees, 2), "net_usdt": round(gross - fees, 2)}


def position_levels(
    config: Dict,
    side: str,
    orders: List[OrderInfo],
    current_sl: Optional[float],
    price: float,
    total_size: float,
    trailing_enabled: bool = True,
    fee_rate: float = DEFAULT_FEE_RATE,
) -> Dict:
    calc = PositionCalculator(config)
    for o in orders:
        calc.add_order(o)
    avg = calc.calculate_average_price(orders)
    long = side == "LONG"
    out: Dict = {
        "price": price,
        "average_price": avg,
        "orders": f"{len(orders)}/{config.get('order_count')}",
        "fee_rate_assumed": fee_rate,
        "now": _net(calc, side, avg, price, total_size, fee_rate),
    }

    # стоп
    if current_sl:
        locked = current_sl > avg if long else current_sl < avg
        out["stop"] = {"price": current_sl, "pct_from_price": _pct(current_sl, price),
                       "in_profit": locked, **_net(calc, side, avg, current_sl, total_size, fee_rate)}
    else:
        out["stop"] = {"price": None, "note": "стопа нет" + (" до заполнения сетки (DCA)" if calc.is_dca() else "")}

    # тейк
    tp_price = calc.take_profit_price(side)
    if tp_price:
        out["take_profit"] = {"price": tp_price, "pct_from_price": _pct(tp_price, price),
                              **_net(calc, side, avg, tp_price, total_size, fee_rate)}
    else:
        tp = config.get("tp_percent")
        if tp is None or tp >= 100:
            out["take_profit"] = {"price": None, "note": "тейка нет — выход по стопу/трейлингу"}
        else:
            out["take_profit"] = {"price": None,
                                  "note": f"тейк {tp}% от средней появится после {config.get('order_count')}-го ордера"}

    # трейлинг: стоп = trailing_sl, как только он лучше текущего стопа (стоп только подтягивается)
    if calc.is_dca() or not config.get("use_trailing"):
        out["trailing"] = {"active": False, "note": "трейлинг выключен" if not calc.is_dca() else "у DCA трейлинга нет"}
    elif not trailing_enabled:
        out["trailing"] = {"active": False, "note": "трейлинг снят для этой позиции вручную (стоп закреплён)"}
    elif len(orders) < 2:
        out["trailing"] = {"active": False, "note": "трейлинг включится после 2-го ордера"}
    else:
        t = config["trailing_percent"] / 100
        if current_sl:
            moves_from = current_sl / (1 - t) if long else current_sl / (1 + t)
            already = price >= moves_from if long else price <= moves_from
        else:
            moves_from, already = price, True
        out["trailing"] = {
            "active": True,
            "trailing_percent": config["trailing_percent"],
            "moves_stop_from_price": moves_from,
            "pct_from_price": _pct(moves_from, price),
            "moving_now": already,
            "profit_when_starts": _net(calc, side, avg, moves_from, total_size, fee_rate),
        }

    # следующий ордер и стоп после него
    if len(orders) < config.get("order_count", 0):
        if calc.is_dca():
            next_price = calc.next_dca_price(side)
        else:
            step = config.get("step_percent", 0) / 100
            last = calc.get_last_order_price()
            next_price = last * (1 + step) if long else last * (1 - step)
        if next_price:
            size = calc.calculate_next_order_size()
            after = PositionCalculator(config)
            for o in [*orders, OrderInfo(len(orders) + 1, next_price, size)]:
                after.add_order(o)
            new_avg = after.calculate_average_price(after.orders)
            new_sl, sl_type = after.calculate_stop_loss(side, after.orders, next_price, trailing_enabled=trailing_enabled)
            out["next_order"] = {
                "number": len(orders) + 1, "price": next_price, "pct_from_price": _pct(next_price, price),
                "size_usdt": round(size, 2), "new_average": new_avg,
                "stop_after": {"price": new_sl or None, "type": sl_type,
                               **(_net(after, side, new_avg, new_sl, total_size + size, fee_rate) if new_sl else {})},
            }
    else:
        out["next_order"] = None
    return out
