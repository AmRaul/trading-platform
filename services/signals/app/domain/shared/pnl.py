def calc_pnl(side: str, entry: float, current: float) -> float:
    if side == "LONG":
        return round((current - entry) / entry * 100, 2)
    return round((entry - current) / entry * 100, 2)
