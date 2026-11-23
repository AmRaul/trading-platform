"""Комплекты бумажного форвард-теста как данные.

Раньше разбор (MCP monthly_review) узнавал комплект по названию бота, а ожидания жили
текстом в промпте и в TODO/7 — переименование бота ломало разбор. Теперь у бота есть
поле forward_test = "<комплект>/<часть>" (например "portfolio/short"), а ожидания и
критерии остановки — здесь, в одном месте, и отдаются API (/api/analytics/forward-test).

Цифры записаны ДО старта (TODO/7-paper-forward-test.md) и задним числом не меняются.
Если что-то пересматривается — новая запись в TODO/7 с датой и причиной.
"""
from typing import Dict, Optional, Tuple

FORWARD_TEST_SETS: Dict[str, Dict] = {
    "portfolio": {
        "title": "Основной портфель",
        "role": "portfolio",  # цифры и критерии остановки форвард-теста считаются только по нему
        "started": "2026-11-18",
        "ends": "2027-02-18",
        "deposit_usdt": 10700,
        "expectations": {
            "annual_return_pct": 15.8,
            "max_drawdown_pct": 14.4,
            "worst_month_pct": -7.4,
            "month_p5_pct": -2.6,
            "month_median_pct": 0.5,
            "month_p95_pct": 8.6,
            "three_months_normal_pct": [-4.0, 15.0],
            "worst_three_months_history_pct": -10.0,
            "trades_per_month": 43,
        },
        "stop_criteria": [
            "просадка портфеля > 20% ($2 140) от пика",
            "результат за любые 3 месяца хуже −10%",
            "просадка шорт-части > 35% ($1 750) или MRC-части > 25% ($1 425)",
            "сверка с бэктестом: другой вход или выход (mismatch), а не просто цена",
        ],
        "not_a_reason": [
            "серия убыточных сделок у шорта (прибыльна только полная сетка из 4 ордеров)",
            "месяц без сделок у MRC",
            "1–2 месяца в минусе в пределах −7%",
            "«новая идея получше» — в журнал гипотез, не запускается",
        ],
        "final": "доходность/просадка ≥ 0.6 и ни один критерий не сработал → край подтверждён",
        "parts": {
            "mrc": {
                "title": "MRC DCA · BTC 15m Long · Консервативный",
                "deposit_usdt": 5700,
                "max_drawdown_stop_pct": 25,
                "expectations": {"annual_return_pct": 10.1, "max_drawdown_pct": 21.4, "worst_month_pct": -9.9,
                                 "trades_per_month": 4},
                "notes": "при BTC ниже EMA200 1d не торгует — ноль сделок за месяц нормален (trend_ok=False)",
            },
            "short": {
                "title": "Шорт альтов · пирамидинг · 5 монет · Консервативный",
                "deposit_usdt": 5000,
                "max_drawdown_stop_pct": 35,
                "expectations": {"annual_return_pct": 22.3, "max_drawdown_pct": 30.8, "worst_month_pct": -15.8,
                                 "months_positive_pct": 44, "trades_per_month": 39, "avg_trade_hours": 29},
                "notes": "прибыль только от сделок с полной сеткой (4 ордера); 1–2 ордера — убыток, это норма",
            },
        },
    },
    "take6": {
        "title": "Шорт альтов · Тейк 6%",
        "role": "parallel",  # рядом с портфелем, в его цифры и критерии не входит
        "started": "2026-11-19",
        "ends": "2027-02-18",
        "deposit_usdt": 5000,
        "compare_with": "portfolio/short",
        "expectations": {"annual_return_pct": 21.2, "max_drawdown_pct": 21.6, "worst_month_pct": -11.7,
                         "trades_per_month": 47, "avg_trade_hours": 20},
        "final": ("переходит в основную версию, только если на живых данных не хуже основного шорта по "
                  "доходности/просадке и сделки с тейком совпадают по механике с бэктестом"),
        "notes": "тот же шорт + тейк 6% от средней после 4-го ордера; сравнивать с основным шортом за общий период",
        "parts": {"short": {"title": "Шорт альтов · пирамидинг · 5 монет · Тейк 6%", "deposit_usdt": 5000}},
    },
    # Записано 2026-11-23 до старта (журнал разборов #8, research/donchian_long_card.py).
    "donchian": {
        "title": "Лонг · пробой Donchian 20/10 · 6 монет",
        "role": "parallel",
        "started": "2026-11-23",
        "ends": "2027-02-18",
        "deposit_usdt": 6000,
        "compare_with": "portfolio/short",
        "expectations": {
            "annual_return_pct": 57.0,
            "max_drawdown_pct": 33.1,  # от пика equity; от пика прибыли — до 110% депозита (2022)
            "worst_month_pct": -15.0,
            "month_p5_pct": -9.8,
            "month_median_pct": -0.6,
            "month_p95_pct": 44.0,
            "months_positive_pct": 42,
            "three_months_normal_pct": [-11.6, 67.6],
            "worst_three_months_history_pct": -17.3,
            "trades_per_month": 3.1,
            "avg_trade_days": 21.4,
            "win_rate_pct": 39.6,
        },
        "stop_criteria": [
            "результат за любые 3 месяца хуже −20% ($1 200) — хуже худших 3 месяцев истории (−17.3%)",
            "сверка: вход не на пробое максимума 20 дневок или выход не на пробое минимума 10 дневок",
        ],
        "not_a_reason": [
            "серия мелких убытков и медианный месяц около нуля — прибыль дают редкие длинные росты",
            "ни одной сделки за месяц: в боковике цена не выходит за канал",
            "убыток одной сделки 20–35%: стопа нет, выход только по каналу",
        ],
        "final": ("кандидат в основной портфель как пара к шорту альтов, если связка «шорт + Donchian» "
                  "за период теста не хуже одного шорта по доходности/просадке и сделки совпадают с каналом"),
        "notes": ("сам по себе тяжёлый (2022 −36%); смысл — отрицательная корреляция с шортом альтов "
                  "(−0.22 / −0.15 по месяцам). Выход по каналу проверяет планировщик на закрытии часа"),
        "parts": {"long": {"title": "Лонг · пробой Donchian 20/10 · 6 монет · Базовый", "deposit_usdt": 6000,
                           "max_drawdown_stop_pct": 20}},
    },
}


def parse(value: Optional[str]) -> Optional[Tuple[str, str]]:
    """"portfolio/short" → ("portfolio", "short"); неизвестное — None."""
    if not value or "/" not in value:
        return None
    set_key, part = value.split("/", 1)
    if part not in FORWARD_TEST_SETS.get(set_key, {}).get("parts", {}):
        return None
    return set_key, part


def valid_values() -> list:
    return [f"{k}/{p}" for k, s in FORWARD_TEST_SETS.items() for p in s["parts"]]


def from_bot_name(name: str, exchange: str) -> Optional[str]:
    """Комплект по названию — только для первичной разметки существующих ботов (миграция)."""
    if exchange != "paper":
        return None
    if name.startswith("MRC DCA · BTC 15m Long · Консервативный"):
        return "portfolio/mrc"
    if name.startswith("Шорт альтов · пирамидинг · 5 монет · Консервативный"):
        return "portfolio/short"
    if name.startswith("Шорт альтов · пирамидинг · 5 монет · Тейк 6%"):
        return "take6/short"
    if name.startswith("Лонг · пробой Donchian 20/10 · 6 монет"):
        return "donchian/long"
    return None
