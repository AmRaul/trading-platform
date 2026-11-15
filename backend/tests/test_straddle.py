"""Straddle-калькулятор на примерах из TODO/6: ордер $100, шаг 2%, 4 ордера (вход + 3 добора)."""
import pytest

from app.domain.trading.straddle import (
    ADD, CLOSE, FINISH, LONG, OPEN, SHORT, StraddleCalculator, StraddleState,
)

CFG = {"entry_size_usdt": 100, "step_percent": 2.0, "order_count": 4, "pyramiding_multiplier": 1.0,
       "phase2_after_steps": 3, "add_stop_steps": 1.0, "trailing_percent": 5.0, "tp_percent": 100,
       "time_stop_minutes": 240, "max_rearms": 1}


def run(calc, st, prices, now=0.0):
    log = []
    for p in prices:
        calc.update_marks(st, p)
        while (a := calc.decide(st, p, now)) is not None:
            pnl = calc.apply(st, a, p, now)
            log.append((a.kind, a.side, a.reason, p, round(pnl, 4)))
            if st.done:
                return log
    return log


def launched(cfg=CFG, price=100):
    calc = StraddleCalculator(cfg)
    st = calc.start(price, 0)
    assert run(calc, st, [price]) == [(OPEN, LONG, "PAIR", price, 0), (OPEN, SHORT, "PAIR", price, 0)]
    return calc, st


def test_launch_opens_both_sides():
    _, st = launched()
    assert st.legs == {LONG: [[100, 100]], SHORT: [[100, 100]]} and st.phase == 0


def test_at_104_long_plus_6_short_minus_4():
    calc, st = launched()
    run(calc, st, [102, 104])
    u = st.unrealized(104)
    assert u[LONG] == pytest.approx(5.96, abs=0.01) and u[SHORT] == pytest.approx(-4)
    assert st.total(104) == pytest.approx(1.96, abs=0.01)
    assert st.stop == pytest.approx(102.99, abs=0.01)  # средняя доборов: итог ≈ 0
    assert len(st.legs[SHORT]) == 1                     # минусовая не добирает


def test_trend_phase2_closes_loser_breakeven_then_trailing():
    calc, st = launched()
    log = run(calc, st, [102, 104, 106])
    assert [(k, s, r) for k, s, r, _, _ in log] == [
        (ADD, LONG, "ADD"), (ADD, LONG, "ADD"), (ADD, LONG, "ADD"), (CLOSE, SHORT, "PHASE2")]
    assert log[-1][4] == pytest.approx(-6)
    assert st.phase == 2 and st.stop == pytest.approx(104.5, abs=0.01)  # безубыток конструкции
    log = run(calc, st, [115, 109.25])
    assert log[-1][:3] == (CLOSE, LONG, "TRAILING_STOP") and st.done
    expected = sum(100 * (109.25 / p - 1) for p in (100, 102, 104, 106)) - 6
    assert st.realized == pytest.approx(expected)


def test_whipsaw_closes_adds_and_reopens_pair():
    calc, st = launched()
    log = run(calc, st, [102, 101, 100])
    assert [(k, s, r) for k, s, r, _, _ in log] == [
        (ADD, LONG, "ADD"), (CLOSE, LONG, "WHIPSAW"), (OPEN, LONG, "PAIR")]
    assert log[1][4] == pytest.approx(-1.96, abs=0.01)  # минус одного добора
    assert st.legs[LONG] == [[100, 100]] and len(st.legs[SHORT]) == 1 and st.rearms == 1
    log = run(calc, st, [99, 98])
    assert log == [(ADD, SHORT, "ADD", 98, 0.0)] and st.working == SHORT


def test_whipsaw_above_first_level_needs_reset():
    calc, st = launched()
    log = run(calc, st, [102, 104, 102.9, 102.5])
    assert [(k, r) for k, _, r, _, _ in log] == [(ADD, "ADD"), (ADD, "ADD"), (CLOSE, "WHIPSAW"), (OPEN, "PAIR")]
    assert run(calc, st, [102.4]) == []                 # нового хода нет, пока не вернулись к точке
    assert run(calc, st, [101, 102.2]) == [(ADD, LONG, "ADD", 102.2, 0.0)]


def test_add_stop_half_step():
    calc, st = launched({**CFG, "add_stop_steps": 0.5})
    log = run(calc, st, [102, 101])
    assert log[1][:3] == (CLOSE, LONG, "WHIPSAW")
    assert st.total(101) == pytest.approx(-0.98, abs=0.01)  # пила на полшага стоит полшага


def test_max_rearms_closes_everything():
    calc, st = launched({**CFG, "max_rearms": 0})
    log = run(calc, st, [102, 100])
    assert log[-1][:3] == (CLOSE, LONG, "WHIPSAW") and st.done and st.exit_reason == "MAX_REARMS"
    # шорт ещё открыт — исполнитель закрывает остаток по done (см. StraddleRunner)
    assert st.legs[SHORT]


def test_time_stop_closes_both():
    calc, st = launched()
    assert run(calc, st, [101, 99.5], now=100) == []
    log = run(calc, st, [100.3], now=240 * 60)
    assert [(k, s, r) for k, s, r, _, _ in log] == [(CLOSE, LONG, "TIME_STOP"), (CLOSE, SHORT, "TIME_STOP")]
    assert st.done and st.realized == pytest.approx(0.0, abs=0.01)  # пара в нуле — потеряли только комиссии


def test_take_profit_in_phase2():
    calc, st = launched({**CFG, "tp_percent": 5})
    run(calc, st, [102, 104, 106])
    log = run(calc, st, [107, 108.5])  # средняя лонга ≈ 102.97 → тейк ≈ 108.12
    assert log[-1][:3] == (CLOSE, LONG, "TP") and st.done


def test_stop_only_tightens():
    calc, st = launched()
    run(calc, st, [102, 104, 106, 120])
    assert st.stop == pytest.approx(114)  # трейлинг 5% от 120
    run(calc, st, [118, 116])
    assert st.stop == pytest.approx(114)


def test_price_gap_fills_levels_one_by_one():
    calc, st = launched()
    log = run(calc, st, [107])
    assert [k for k, *_ in log] == [ADD, ADD, ADD, CLOSE]


def test_state_roundtrip():
    calc, st = launched()
    run(calc, st, [102, 104])
    assert StraddleState.from_dict(st.to_dict()) == st
