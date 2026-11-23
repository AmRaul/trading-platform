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


def test_climax_mask_marks_bullish_volume_spike():
    import pandas as pd
    import hypothesis_runner as hr
    n = 100
    df = pd.DataFrame({"open": [10.0] * n, "close": [9.9] * n, "volume": [100.0] * n})
    df.loc[98, ["close", "volume"]] = [10.5, 400.0]   # рост на объёме ×4 — кульминация
    df.loc[99, ["close", "volume"]] = [9.5, 500.0]    # падение на объёме — против лонга, не против шорта
    m = hr.climax_mask(df, 3.0)
    assert m[98] and not m[99] and m.sum() == 1


def test_climax_params_off_by_default():
    import hypothesis_runner as hr
    p = hr.resolve("alt_short", {})
    assert p["climax_block_hours"] == 0 and p["climax_trail_u"] == 0.0


def test_climax_mask_for_long_marks_bearish_spike():
    import pandas as pd
    import hypothesis_runner as hr
    n = 120
    df = pd.DataFrame({"open": [10.0] * n, "close": [10.0] * n, "volume": [1.0] * n})
    df.loc[110, ["open", "close", "volume"]] = [10.0, 9.0, 5.0]
    assert hr.climax_mask(df, 3.0, "LONG")[110] and not hr.climax_mask(df, 3.0, "SHORT")[110]


def test_trend_long_and_coin_params():
    import hypothesis_runner as hr
    p = hr.resolve("trend_long", {})
    assert p["coins"] == ["ETH"] and hr.deposit_of("trend_long", p) == 1000.0
    assert hr.deposit_of("trend_long", hr.resolve("trend_long", {"coins": ["ETH", "SOL"]})) == 2000.0
    m = hr.resolve("mrc_dca", {"coins": ["btc", "ethusdt"]})
    assert m["coins"] == ["BTC", "ETH"] and hr.deposit_of("mrc_dca", m) == 11400.0
    assert hr.resolve("trend_long", {})["btc_regime"] == 0 and hr.resolve("alt_short", {})["min_rel_pct"] == -100.0
    assert hr.deposit_of("alt_short", hr.resolve("alt_short", {})) == 5000.0
