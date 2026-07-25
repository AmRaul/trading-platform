import numpy as np
from typing import List


def ema(values: List[float], period: int) -> List[float]:
    if len(values) < period:
        return []
    arr = np.array(values, dtype=float)
    k = 2.0 / (period + 1)
    out = np.empty(len(arr))
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = arr[i] * k + out[i - 1] * (1 - k)
    return out.tolist()


def ema21(closes: List[float]) -> float:
    result = ema(closes, 21)
    return result[-1] if result else 0.0


def ema21_series(closes: List[float]) -> List[float]:
    return ema(closes, 21)
