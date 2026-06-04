from typing import List


def ema(values: List[float], period: int) -> List[float]:
    if len(values) < period:
        return []
    import pandas as pd
    s = pd.Series(values)
    result = s.ewm(span=period, adjust=False).mean()
    return result.tolist()


def ema21(closes: List[float]) -> float:
    result = ema(closes, 21)
    return result[-1] if result else 0.0


def ema21_series(closes: List[float]) -> List[float]:
    return ema(closes, 21)
