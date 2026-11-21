"""Правила журнала гипотез: что показывать после прогона и как читать отложенный период.

Обучающий период (до 07.2024) — на нём идею можно смотреть и обсуждать. Отложенный
(после) — экзамен: открывается один раз, после того как по обучающему решено
«проходит / не проходит». Чем больше попыток у одной идеи, тем меньше стоит экзамен:
перебор вариантов сам по себе находит «удачный» на любых данных.
"""
from typing import Dict, Optional

METRICS = ("annual_return_pct", "max_drawdown_pct", "ratio", "worst_month_pct", "months_positive_pct",
           "trades_per_month", "win_rate_pct", "full_grid_pct")
OVERFIT_ATTEMPTS = 3
FROZEN_NOTE = ("Это кандидат в СЛЕДУЮЩИЙ форвард-тест, не изменение текущих ботов: бумажные боты "
               "заморожены до 2027-02-18.")


def idea_key(base: str, changes: Dict) -> str:
    """Идея = стратегия + какие параметры меняли (значения — это попытки одной идеи)."""
    return f"{base}:{','.join(sorted(changes)) or 'база'}"


def compare(variant: Dict, baseline: Dict) -> Dict:
    """Метрики варианта, базы и разница по одному периоду."""
    out = {}
    for m in METRICS:
        v, b = variant.get(m), baseline.get(m)
        if v is None and b is None:
            continue
        out[m] = {"variant": v, "base": b, "diff": round(v - b, 2) if v is not None and b is not None else None}
    return out


def train_view(result: Dict, attempt: int) -> Dict:
    """Что видно до решения: только обучающий период (и по годам внутри него)."""
    view = {
        "period": "train 2021-01 → 2024-07",
        "train": compare(result["variant"]["train"], result["baseline"]["train"]),
        "yearly_train_pct": {"variant": result["variant"].get("yearly_train_pct"),
                             "base": result["baseline"].get("yearly_train_pct")},
        "params": result.get("params"),
        "data_sources": result.get("data_sources"),
        "holdout": "скрыт до решения по обучающему периоду (hypothesis_reveal)",
    }
    if attempt >= OVERFIT_ATTEMPTS:
        view["warning"] = overfit_warning(attempt)
    return view


def overfit_warning(attempt: int) -> str:
    return (f"Попытка №{attempt} этой идеи: перебор параметров сам находит «удачный» вариант — "
            f"отложенному периоду доверять меньше; сильнее, если улучшение небольшое.")


def verdict(result: Dict, train_decision: str, attempt: int) -> Dict:
    """Итог после отложенного периода. Подтвердилась — на отложенном лучше базы по
    доходность/просадка и доходность не хуже базы больше чем на 20%."""
    v, b = result["variant"]["holdout"], result["baseline"]["holdout"]
    better_ratio = (v.get("ratio") or 0) >= (b.get("ratio") or 0)
    ann_v, ann_b = v.get("annual_return_pct") or 0, b.get("annual_return_pct") or 0
    keeps_return = ann_v >= ann_b - abs(ann_b) * 0.2
    confirmed = better_ratio and keeps_return
    out = {
        "holdout": compare(v, b),
        "confirmed": confirmed,
        "summary": ("подтвердилась на отложенном периоде" if confirmed else "не подтвердилась на отложенном периоде"),
        "train_decision": train_decision,
        "consistent_with_train": (train_decision == "passes") == confirmed,
        "note": FROZEN_NOTE,
    }
    if attempt >= OVERFIT_ATTEMPTS:
        out["warning"] = overfit_warning(attempt)
    return out
