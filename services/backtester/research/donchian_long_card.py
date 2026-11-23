"""
JSON бэктеста для карточки готовой стратегии «Лонг · пробой Donchian 20/10 · 6 монет»
(backend/app/domain/ready_strategies/data/). Формат — как у alt_short_pyramid_card.py.

6 ботов (BTC ETH SOL AVAX LINK XRP), по одному на монету, позиция $1000 на каждый при депозите $6000
(в сумме 1:1). Вход: close 1h выше максимума 20 закрытых дневок; выход: close 1h ниже минимума
10 дневок — по open следующего часа. Стопа и тейка нет. Расчёт — long_trend_classic.simulate.

Запуск (из services/backtester, PYTHONPATH=.:research):
    python research/donchian_long_card.py --out ../../backend/app/domain/ready_strategies/data/donchian_long_6.json
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import hypothesis_runner as hr
import long_trend_classic as lt

DEPOSIT = 1000.0 * len(lt.COINS)


def coin_run(coin):
    h1 = lt.load(coin)
    e, x, t = lt.signals(h1, "V2_donch20_10")
    eq, tr = lt.simulate(h1, np.nan_to_num(e, nan=0).astype(bool), np.nan_to_num(x, nan=0).astype(bool), t)
    return eq[eq.index >= hr.START], tr


def build():
    eqs, trs = zip(*(coin_run(c) for c in lt.COINS))
    idx = eqs[0].index
    for e in eqs[1:]:
        idx = idx.union(e.index)
    pnl = sum(e.reindex(idx).ffill().fillna(0) for e in eqs)
    equity = DEPOSIT + pnl
    peak = np.maximum.accumulate(equity.values)
    dd = pd.Series((peak - equity.values) / peak * 100, index=idx)
    tr = pd.concat([t for t in trs if len(t)], ignore_index=True)
    end = str(idx[-1].date())
    years = (idx[-1] - idx[0]).days / 365.25
    total = float(pnl.iloc[-1]) / DEPOSIT * 100

    def pct_between(a, b):
        s = pnl[(pnl.index >= pd.Timestamp(a)) & (pnl.index < pd.Timestamp(b))]
        if not len(s):
            return 0.0
        before = pnl[pnl.index < pd.Timestamp(a)]
        start = float(before.iloc[-1]) if len(before) else 0.0
        return round((float(s.iloc[-1]) - start) / DEPOSIT * 100, 1)

    monthly = pd.DataFrame({"equity": equity, "dd": dd}).resample("ME").last()
    train = hr.period_stats(equity, DEPOSIT, tr, hr.START, hr.SPLIT)
    hold = hr.period_stats(equity, DEPOSIT, tr, hr.SPLIT, hr.END)
    return {
        "params": {
            "symbols": [f"{c}USDT" for c in lt.COINS],
            "side": "LONG",
            "timeframe": "1h",
            "donchian": {"entry_days": 20, "exit_days": 10, "timeframe": "1D"},
            "order_count": 1,
            "deposit": DEPOSIT,
            "first_order": 1000.0,
        },
        "period": {"start": str(idx[0].date()), "end": end},
        "metrics": {
            "total_return_pct": round(total, 1),
            "avg_annual_return_pct": round(total / years, 1),
            "max_drawdown_pct": round(float(dd.max()), 1),
            "max_drawdown_from_deposit_pct": round(float((np.maximum.accumulate(pnl.values) - pnl.values).max())
                                                   / DEPOSIT * 100, 1),
            "trades": int(len(tr)),
            "win_rate_pct": round(float((tr["pnl"] > 0).mean() * 100), 1),
            # выход — по каналу; «стопы» — убыточные выходы, как в карточке пирамиды
            "stops": int((tr["pnl"] <= 0).sum()),
            "full_grid_fills": int(len(tr)),  # один ордер на сделку
            "avg_trade_hours": round(float(((tr["exit"] - tr["entry"]).dt.total_seconds() / 3600).mean()), 1),
            "max_trade_days": round(float(((tr["exit"] - tr["entry"]).dt.total_seconds() / 86400).max()), 1),
            "liquidations": 0,
            "period_2021_2023_pct": pct_between("2021-01-01", "2024-01-01"),
            "period_2024_2026_pct": pct_between("2024-01-01", "2027-01-01"),
            "train": train,
            "holdout": hold,
        },
        "yearly": [{"year": int(y), "return_pct": pct_between(f"{y}-01-01", f"{y + 1}-01-01")}
                   for y in sorted(set(idx.year))],
        "equity_curve": [{"date": str(t.date()), "equity": round(float(r.equity), 2),
                          "drawdown_pct": round(float(r.dd), 2)} for t, r in monthly.iterrows()],
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    result = build()
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in result["metrics"].items()}, ensure_ascii=False, indent=1))
    print([y["return_pct"] for y in result["yearly"]])
