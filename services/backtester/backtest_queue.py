"""Очередь тяжёлых задач бэктестера: не больше N одновременно, остальные ждут по порядку.

Раньше каждый /api/run-backtest запускал свой поток без ограничений: два-три прогона
разом делили одно ядро контейнера (cpus: 1.0) и шли втрое дольше, а с несколькими
пользователями — без предела. Оптимизации уже шли через свою очередь (optimization_queue).

Redis не нужен: бэктестер — один процесс gunicorn (--workers 1), очереди в памяти хватает.
"""
import threading
from typing import List, Optional


class FairSlots:
    """N слотов, выдаются строго в порядке очереди (обычный семафор порядок не гарантирует)."""

    def __init__(self, slots: int):
        self.slots = max(1, int(slots))
        self.active = 0
        self.waiting: List[str] = []
        self._cv = threading.Condition()

    def acquire(self, task_id: str, timeout: Optional[float] = None) -> bool:
        with self._cv:
            self.waiting.append(task_id)
            ok = self._cv.wait_for(lambda: self.waiting[0] == task_id and self.active < self.slots, timeout)
            if not ok:
                self.waiting.remove(task_id)
                self._cv.notify_all()
                return False
            self.waiting.pop(0)
            self.active += 1
            self._cv.notify_all()
            return True

    def release(self) -> None:
        with self._cv:
            self.active = max(0, self.active - 1)
            self._cv.notify_all()

    def position(self, task_id: str) -> Optional[int]:
        """Место в очереди (1 — следующий) или None — не ждёт."""
        with self._cv:
            return self.waiting.index(task_id) + 1 if task_id in self.waiting else None

    def stats(self) -> dict:
        with self._cv:
            return {"slots": self.slots, "running": self.active, "waiting": len(self.waiting)}
