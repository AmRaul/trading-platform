"""Проблемы исполнения по ботам: биржа не подтвердила вход/добор/закрытие, на бирже
позиция, которой нет в базе. Живут в памяти процесса бэкенда (он один), попадают
в /api/analytics/bots-health как issues, а оттуда алертер шлёт их в Telegram.

Ключ — вид проблемы: повтор той же проблемы заменяет текст, а не копит дубликаты;
успешная операция снимает свою проблему (clear(bot_id, "close")).
"""
import time
from typing import Dict, List, Optional, Tuple

_issues: Dict[int, Dict[str, Tuple[str, float]]] = {}  # bot_id -> вид -> (текст, истекает в; inf — никогда)


def report(bot_id: int, kind: str, text: str, ttl_sec: Optional[float] = None) -> None:
    """ttl_sec — для проблем, которые некому снять (нечем проверить, что их исправили)."""
    expires = time.time() + ttl_sec if ttl_sec else float("inf")
    _issues.setdefault(bot_id, {})[kind] = (text, expires)


def clear(bot_id: int, kind: Optional[str] = None) -> None:
    if kind is None:
        _issues.pop(bot_id, None)
        return
    bucket = _issues.get(bot_id)
    if bucket:
        bucket.pop(kind, None)
        if not bucket:
            _issues.pop(bot_id, None)


def issues_for(bot_id: int) -> List[str]:
    now = time.time()
    return [text for text, expires in (_issues.get(bot_id) or {}).values() if expires > now]


def reset() -> None:
    """Для тестов."""
    _issues.clear()
