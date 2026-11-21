"""Ограничение попыток входа против подбора пароля: MAX_FAILURES неудачных попыток за
WINDOW_SEC по паре (IP, логин) — дальше 429 до конца окна. В памяти процесса (бэкенд один)."""
import time
from typing import Dict, List, Optional, Tuple

MAX_FAILURES = 10
WINDOW_SEC = 15 * 60

_failures: Dict[Tuple[str, str], List[float]] = {}


def _recent(key: Tuple[str, str], now: float) -> List[float]:
    hits = [t for t in _failures.get(key, []) if now - t < WINDOW_SEC]
    if hits:
        _failures[key] = hits
    else:
        _failures.pop(key, None)
    return hits


def retry_after(ip: str, username: str, now: Optional[float] = None) -> Optional[int]:
    """Сколько секунд ждать, если попытки исчерпаны; None — можно пробовать."""
    now = now or time.time()
    hits = _recent((ip, username.lower()), now)
    if len(hits) < MAX_FAILURES:
        return None
    return int(WINDOW_SEC - (now - hits[0])) + 1


def failed(ip: str, username: str, now: Optional[float] = None) -> None:
    _failures.setdefault((ip, username.lower()), []).append(now or time.time())


def succeeded(ip: str, username: str) -> None:
    _failures.pop((ip, username.lower()), None)


def reset() -> None:
    _failures.clear()
