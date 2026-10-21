"""
Straddle («Мани Батон», TODO/6): при запуске открываются LONG и SHORT по X.
Рабочая — сторона, куда пошла цена: она добирает каждые step% от точки запуска,
минусовая не добирает и держится как страховка.

Фазы:
  0 — пара открыта, доборов нет; стопа нет (страхует вторая сторона).
  1 — у рабочей стороны есть доборы. Стоп рабочей стороны: в точке запуска
      (add_stop_steps шагов от первого добора), с 2 доборов — не ниже средней
      доборов (конструкция в безубытке), плюс трейлинг. Стоп сработал (пила) —
      рабочая сторона закрывается целиком и тут же переоткрывается на X: пара
      снова в нуле, зафиксирован только минус доборов.
  2 — цена ушла на phase2_after_steps шагов: минусовая сторона закрывается,
      стоп рабочей — безубыток конструкции этого хода, дальше трейлинг (и тейк,
      если tp_percent < 100).
Стоп по времени: нет фазы 2 за time_stop_minutes — закрыть обе стороны.
После пилы новый ход засчитывается только после возврата цены между уровнями ±1 шаг.

Уровни линейны от точки запуска: k-й уровень = anchor × (1 ± k·step%).
Калькулятор чистый: decide() решает, apply() применяет исполнение.
"""
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

LONG, SHORT = "LONG", "SHORT"
SIDES = (LONG, SHORT)
OPEN, ADD, CLOSE, FINISH = "OPEN", "ADD", "CLOSE", "FINISH"
NO_TP_PERCENT = 100.0


def _dir(side: str) -> int:
    return 1 if side == LONG else -1


def _opposite(side: str) -> str:
    return SHORT if side == LONG else LONG


def leg_pnl(orders: List[List[float]], side: str, price: float) -> float:
    d = _dir(side)
    return sum(u * d * (price / p - 1) for p, u in orders)


def avg_price(orders: List[List[float]]) -> float:
    qty = sum(u / p for p, u in orders)
    return sum(u for _, u in orders) / qty if qty else 0.0


@dataclass
class StraddleAction:
    kind: str                   # OPEN / ADD / CLOSE / FINISH
    side: Optional[str] = None
    usdt: float = 0.0
    reason: str = ""


@dataclass
class StraddleState:
    anchor: float
    started_at: float                       # epoch сек.
    legs: Dict[str, List[List[float]]] = field(default_factory=lambda: {LONG: [], SHORT: []})
    working: Optional[str] = None           # сторона с доборами
    adds: int = 0
    phase: int = 0
    stop: float = 0.0                       # стоп рабочей стороны
    extreme: float = 0.0
    rearms: int = 0
    reset_needed: bool = False
    cycle_realized: float = 0.0             # зафиксировано за текущий ход (с последней пилы)
    realized: float = 0.0                   # зафиксировано за всю конструкцию, USDT без комиссий
    done: bool = False
    exit_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StraddleState":
        return cls(**d)

    def unrealized(self, price: float) -> Dict[str, float]:
        return {s: leg_pnl(self.legs[s], s, price) for s in SIDES}

    def total(self, price: float) -> float:
        return self.realized + sum(self.unrealized(price).values())


class StraddleCalculator:
    def __init__(self, config: dict):
        self.entry = float(config["entry_size_usdt"])
        self.step = float(config["step_percent"])
        # как у пирамидинга: ордеров на рабочей стороне вместе со входом
        self.max_adds = max(int(config.get("order_count", 4)) - 1, 1)
        self.mult = float(config.get("pyramiding_multiplier", 1.0))
        self.phase2_steps = int(config.get("phase2_after_steps", 3))
        self.add_stop_steps = float(config.get("add_stop_steps", 1.0))
        self.trailing = float(config["trailing_percent"]) if config.get("use_trailing", True) else 0.0
        tp = config.get("tp_percent")
        self.tp = float(tp) if tp is not None and tp < NO_TP_PERCENT else None
        minutes = config.get("time_stop_minutes")
        self.time_stop = float(minutes) * 60 if minutes else None
        self.max_rearms = int(config.get("max_rearms", 1))

    def level(self, anchor: float, side: str, k: float) -> float:
        return anchor * (1 + _dir(side) * k * self.step / 100)

    def add_size(self, k: int) -> float:
        return self.entry * self.mult ** k

    @staticmethod
    def _reached(side: str, price: float, level: float) -> bool:
        return _dir(side) * (price - level) >= 0

    def start(self, price: float, now: float) -> StraddleState:
        """Запуск: пустая пара в точке price — decide() сразу вернёт OPEN обеих сторон."""
        return StraddleState(anchor=price, started_at=now)

    def decide(self, st: StraddleState, price: float, now: float) -> Optional[StraddleAction]:
        """Одно следующее действие на этой цене; после apply decide вызывают снова."""
        if st.done:
            return None
        if self.time_stop is not None and st.phase < 2 and now - st.started_at >= self.time_stop:
            for side in SIDES:
                if st.legs[side]:
                    return StraddleAction(CLOSE, side, reason="TIME_STOP")
            return StraddleAction(FINISH, reason="TIME_STOP")

        w = st.working
        if st.phase == 2:
            if _dir(w) * (price - st.stop) <= 0:
                return StraddleAction(CLOSE, w, reason="TRAILING_STOP")
            if self.tp is not None and self._reached(w, price, avg_price(st.legs[w]) * (1 + _dir(w) * self.tp / 100)):
                return StraddleAction(CLOSE, w, reason="TP")
            if st.adds < self.max_adds and self._reached(w, price, self.level(st.anchor, w, st.adds + 1)):
                return StraddleAction(ADD, w, self.add_size(st.adds + 1), "ADD")
            return None

        # фазы 0–1: обе стороны пары должны быть открыты (запуск, переоткрытие после пилы)
        for side in SIDES:
            if not st.legs[side]:
                return StraddleAction(OPEN, side, self.entry, "PAIR")

        if st.phase == 1:
            if _dir(w) * (price - st.stop) <= 0:
                return StraddleAction(CLOSE, w, reason="WHIPSAW")
            if st.adds < self.max_adds and self._reached(w, price, self.level(st.anchor, w, st.adds + 1)):
                return StraddleAction(ADD, w, self.add_size(st.adds + 1), "ADD")
            if self._reached(w, price, self.level(st.anchor, w, self.phase2_steps)):
                return StraddleAction(CLOSE, _opposite(w), reason="PHASE2")
            return None

        if st.reset_needed:
            return None
        for side in SIDES:
            if self._reached(side, price, self.level(st.anchor, side, 1)):
                return StraddleAction(ADD, side, self.add_size(1), "ADD")
        return None

    def apply(self, st: StraddleState, action: StraddleAction, fill: float, now: float) -> float:
        """Применяет исполненное действие по цене fill. Возвращает PnL закрытия (USDT)."""
        pnl = 0.0
        side = action.side
        if action.kind == OPEN:
            st.legs[side] = [[fill, action.usdt]]
        elif action.kind == ADD:
            st.legs[side].append([fill, action.usdt])
            st.adds += 1
            if st.phase == 0:
                st.working, st.phase, st.extreme, st.stop = side, 1, fill, 0.0
        elif action.kind == CLOSE:
            pnl = leg_pnl(st.legs[side], side, fill)
            st.legs[side] = []
            st.realized += pnl
            st.cycle_realized += pnl
            if action.reason == "WHIPSAW":
                # минус доборов зафиксирован, пара переоткроется на следующем decide
                st.working, st.adds, st.phase, st.stop, st.extreme = None, 0, 0, 0.0, 0.0
                st.cycle_realized = 0.0
                st.rearms += 1
                st.reset_needed = True
                if st.rearms > self.max_rearms:
                    st.done, st.exit_reason = True, "MAX_REARMS"
            elif action.reason == "PHASE2":
                st.phase = 2
            elif not st.legs[LONG] and not st.legs[SHORT]:
                st.done, st.exit_reason = True, action.reason
        elif action.kind == FINISH:
            st.done, st.exit_reason = True, action.reason
        self.update_marks(st, fill)
        return pnl

    def update_marks(self, st: StraddleState, price: float) -> bool:
        """Лучшая цена и стоп рабочей стороны; стоп только подтягивается. True — стоп сдвинулся."""
        w = st.working
        if w is None:
            if st.reset_needed and self.level(st.anchor, SHORT, 1) < price < self.level(st.anchor, LONG, 1):
                st.reset_needed = False
            return False
        d = _dir(w)
        st.extreme = max(st.extreme, price) if d == 1 else min(st.extreme, price)
        orders = st.legs[w]
        if st.phase == 1:
            candidates = [self.level(st.anchor, w, 1 - self.add_stop_steps)]
            if st.adds >= 2:
                candidates.append(avg_price(orders[1:]))      # средняя доборов: итог пары ≈ 0
        else:
            # безубыток хода: рабочая сторона + закрытая минусовая
            size, qty = sum(u for _, u in orders), sum(u / p for p, u in orders)
            candidates = [(size - d * st.cycle_realized) / qty] if qty else []
        if self.trailing:
            candidates.append(st.extreme * (1 - d * self.trailing / 100))
        # не на текущую цену и не за неё — иначе гэп сразу выбьет набранную позицию
        candidates = [c for c in candidates if d * (price - c) > 0]
        if not candidates:
            return False
        new = max(candidates) if d == 1 else min(candidates)
        if st.stop == 0 or d * (new - st.stop) > 0:
            st.stop = new
            return True
        return False
