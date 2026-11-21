"""Очередь бэктестов: не больше N одновременно, строго по порядку, место в очереди."""
import threading
import time

from backtest_queue import FairSlots


def test_runs_in_order_with_limit():
    slots = FairSlots(1)
    started, running, peak = [], [0], [0]
    lock = threading.Lock()
    gate = threading.Event()

    def job(tid):
        slots.acquire(tid)
        try:
            with lock:
                started.append(tid)
                running[0] += 1
                peak[0] = max(peak[0], running[0])
            gate.wait(2)
            time.sleep(0.01)
            with lock:
                running[0] -= 1
        finally:
            slots.release()

    threads = []
    for i in range(4):
        t = threading.Thread(target=job, args=(f"t{i}",))
        t.start()
        threads.append(t)
        time.sleep(0.03)  # t0 занял слот, остальные встали в очередь по порядку
    assert slots.position("t0") is None and slots.position("t1") == 1 and slots.position("t3") == 3
    assert slots.stats() == {"slots": 1, "running": 1, "waiting": 3}
    gate.set()
    for t in threads:
        t.join(3)
    assert started == ["t0", "t1", "t2", "t3"] and peak[0] == 1
    assert slots.stats() == {"slots": 1, "running": 0, "waiting": 0}


def test_two_slots_run_in_parallel():
    slots = FairSlots(2)
    assert slots.acquire("a", timeout=0.1) and slots.acquire("b", timeout=0.1)
    assert slots.acquire("c", timeout=0.05) is False  # третий не влез и ушёл из очереди
    assert slots.position("c") is None
    slots.release()
    assert slots.acquire("c", timeout=0.1)
