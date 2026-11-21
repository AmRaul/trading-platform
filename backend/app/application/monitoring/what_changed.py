"""Что изменилось с прошлой проверки: сравнение двух снимков состояния ботов.

События с временем (вход, добор, закрытие сделки, новый бот) берутся из БД отдельно;
здесь — то, что видно только сравнением: удалённые боты, смена состояния, сдвиг
стопа, изменение плавающего PnL.
"""
from typing import Dict, List, Optional

# Изменение плавающего PnL меньше этого, USDT, — шум, не показываем
PNL_EPS = 0.01


def bot_snapshot(bot, position=None, live: Optional[Dict] = None) -> Dict:
    """Строка снимка по боту. live — состояние позиции из Redis (свежее, чем в БД)."""
    live = live or {}
    row = {
        "name": bot.name, "symbol": bot.symbol, "side": bot.side, "exchange": bot.exchange,
        "state": bot.state, "total_pnl": round(bot.total_pnl or 0.0, 2),
        "position_id": None, "sl": None, "unrealized_pnl": None, "order_count": None,
    }
    if position is not None:
        row.update({
            "position_id": position.id,
            "sl": live.get("current_sl", position.current_sl),
            "unrealized_pnl": round(live.get("unrealized_pnl", position.unrealized_pnl or 0.0), 2),
            "order_count": live.get("order_count", position.order_count),
        })
    return row


def diff(old: Dict[str, Dict], new: Dict[str, Dict]) -> Dict:
    """old/new — {bot_id(str): bot_snapshot}. Ключи строкой: снимок хранится в JSON."""
    added = [{"bot_id": int(k), "name": v["name"]} for k, v in new.items() if k not in old]
    removed = [{"bot_id": int(k), "name": v["name"]} for k, v in old.items() if k not in new]
    state_changes: List[Dict] = []
    stop_moves: List[Dict] = []
    pnl_changes: List[Dict] = []
    for k, now in new.items():
        was = old.get(k)
        if not was:
            continue
        bot_id = int(k)
        if was["state"] != now["state"]:
            state_changes.append({"bot_id": bot_id, "name": now["name"], "from": was["state"], "to": now["state"]})
        same_position = was.get("position_id") and was.get("position_id") == now.get("position_id")
        if same_position and was.get("sl") and now.get("sl") and abs(now["sl"] - was["sl"]) > 1e-12:
            stop_moves.append({
                "bot_id": bot_id, "name": now["name"], "side": now["side"], "from": was["sl"], "to": now["sl"],
                "pct": round((now["sl"] / was["sl"] - 1) * 100, 3),
            })
        if same_position:
            d = (now.get("unrealized_pnl") or 0.0) - (was.get("unrealized_pnl") or 0.0)
            if abs(d) >= PNL_EPS:
                pnl_changes.append({"bot_id": bot_id, "name": now["name"], "from": was.get("unrealized_pnl"),
                                    "to": now.get("unrealized_pnl"), "change": round(d, 2)})

    def total(snap: Dict, field: str) -> float:
        return round(sum((v.get(field) or 0.0) for v in snap.values()), 2)

    return {
        "bots_added": added,
        "bots_removed": removed,
        "state_changes": state_changes,
        "stop_moves": stop_moves,
        "unrealized_changes": sorted(pnl_changes, key=lambda x: -abs(x["change"])),
        "totals": {
            "realized_pnl": {"was": total(old, "total_pnl"), "now": total(new, "total_pnl"),
                             "change": round(total(new, "total_pnl") - total(old, "total_pnl"), 2)},
            "unrealized_pnl": {"was": total(old, "unrealized_pnl"), "now": total(new, "unrealized_pnl"),
                               "change": round(total(new, "unrealized_pnl") - total(old, "unrealized_pnl"), 2)},
        },
    }
