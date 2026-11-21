"""Журнал гипотез: идея и попытки, отложенный период скрыт до решения, итог."""
from app.application.research.hypotheses import compare, idea_key, train_view, verdict


def _period(ann, dd, ratio):
    return {"annual_return_pct": ann, "max_drawdown_pct": dd, "ratio": ratio, "trades_per_month": 40}


RESULT = {
    "params": {"tp_percent": 6},
    "data_sources": {"SOL": "bybit"},
    "variant": {"train": _period(20.8, 21.6, 0.96), "holdout": _period(21.7, 19.8, 1.10), "yearly_train_pct": {"2021": 30}},
    "baseline": {"train": _period(25.2, 24.2, 1.04), "holdout": _period(17.9, 30.8, 0.58), "yearly_train_pct": {"2021": 35}},
}


def test_idea_key_ignores_values():
    assert idea_key("alt_short", {"tp_percent": 6}) == idea_key("alt_short", {"tp_percent": 8})
    assert idea_key("alt_short", {"tp_percent": 6, "sl_percent": 3}) == "alt_short:sl_percent,tp_percent"


def test_train_view_never_shows_holdout():
    view = train_view(RESULT, attempt=1)
    flat = repr(view)
    assert "21.7" not in flat and "17.9" not in flat  # цифры отложенного периода не утекают
    assert view["train"]["ratio"] == {"variant": 0.96, "base": 1.04, "diff": -0.08}
    assert "warning" not in view
    assert "Попытка №3" in train_view(RESULT, attempt=3)["warning"]


def test_verdict_confirmed_and_consistency():
    v = verdict(RESULT, "fails", attempt=1)
    assert v["confirmed"] is True and v["consistent_with_train"] is False  # на обучающем хуже, на отложенном лучше
    assert "2027-02-18" in v["note"]
    worse = {**RESULT, "variant": {**RESULT["variant"], "holdout": _period(10.0, 15.0, 0.67)}}
    v2 = verdict(worse, "passes", attempt=4)
    assert v2["confirmed"] is False and "warning" in v2  # доходность упала больше чем на 20%


def test_compare_skips_missing():
    assert compare({"ratio": 1.0}, {"ratio": 0.5}) == {"ratio": {"variant": 1.0, "base": 0.5, "diff": 0.5}}
