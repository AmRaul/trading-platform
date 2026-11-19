"""
JSON бэктеста для карточки готовой стратегии «Шорт альтов · пирамидинг»
(backend/app/domain/ready_strategies/data/). Формат — как у mrc_dca_trend_long.py.

5 ботов (SOL AVAX LINK ETH XRP) на одном депозите, один бот на монету.
Сигнал и сопровождение — short_portfolio: режим 4h вниз + разворот Supertrend 15m,
живой PositionCalculator, 4 ордера по 0.5%, стоп 2%, трейлинг 1U монеты.

Запуск (backend и research в PYTHONPATH):
    python research/alt_short_pyramid_card.py --first-order 250 --out .../alt_short_pyramid_5.json
"""
import argparse
import json
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

import donchian_pyramid as dp
import short_portfolio as sp

COINS = ['SOL', 'AVAX', 'LINK', 'ETH', 'XRP']
DEPOSIT = 5000.0
STEP = 'p0.5'


TP = 100.0


def coin_cfg(df, step):
    cfg = dp.bot_config(0, 4, False, None)
    cfg.update(entry_size_usdt=sp.ENTRY, tp_percent=TP, step_percent=0.5, sl_initial=2.0, sl_after_order3=2.0,
               trailing_percent=round(dp.vol_unit(df), 1))
    return cfg


def report(first_order, trades_by_coin, trailing):
    pnl, taken, _ = sp.portfolio(trades_by_coin, len(COINS), 'first')
    idx = sp.GRID_IDX
    equity = DEPOSIT + pnl
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / peak * 100

    def pct_between(a, b):
        ia = int(np.searchsorted(idx.values, np.datetime64(a)))
        ib = min(int(np.searchsorted(idx.values, np.datetime64(b))), len(idx)) - 1
        return round(float(pnl[ib] - pnl[ia]) / DEPOSIT * 100, 1)

    tr = pd.DataFrame([{'entry': idx[t[0]], 'exit': idx[t[1]], 'pnl': t[2], 'orders': t[3]} for _, t in taken])
    hours = (tr['exit'] - tr['entry']).dt.total_seconds() / 3600
    span_years = (idx[-1] - idx[0]).days / 365.25
    total = float(pnl[-1]) / DEPOSIT * 100
    monthly = pd.DataFrame({'equity': equity, 'dd': dd}, index=idx).resample('ME').last()
    end = str(idx[-1].date())

    return {
        'params': {
            'symbols': [f'{c}USDT' for c in COINS],
            'side': 'SHORT',
            'timeframe': '15m',
            'regime': {'timeframe': '4h', 'ema_fast': 50, 'ema_slow': 200},
            'supertrend': {'period': 10, 'mult': 3.0},
            'order_count': 4,
            'step_percent': 0.5,
            'sl_percent': 2.0,
            'trailing_percent': trailing,
            'deposit': DEPOSIT,
            'first_order': first_order,
        },
        'period': {'start': str(idx[0].date()), 'end': end},
        'metrics': {
            'total_return_pct': round(total, 1),
            'avg_annual_return_pct': round(total / span_years, 1),
            'max_drawdown_pct': round(float(dd.max()), 1),
            'trades': int(len(tr)),
            'win_rate_pct': round(float((tr['pnl'] > 0).mean() * 100), 1),
            # выход у пирамидинга всегда по стопу/трейлингу — считаем убыточные выходы
            'stops': int((tr['pnl'] <= 0).sum()),
            'full_grid_fills': int((tr['orders'] == 4).sum()),
            'avg_trade_hours': round(float(hours.mean()), 1),
            'max_trade_days': round(float(hours.max() / 24), 1),
            'liquidations': int((equity <= 0).any()),
            'period_2021_2023_pct': pct_between('2021-01-01', '2024-01-01'),
            'period_2024_2026_pct': pct_between('2024-01-01', end),
        },
        'yearly': [{'year': int(y), 'return_pct': pct_between(f'{y}-01-01', f'{y + 1}-01-01')}
                   for y in sorted(set(idx.year))],
        'equity_curve': [{'date': str(t.date()), 'equity': round(float(r.equity), 2),
                          'drawdown_pct': round(float(r.dd), 2)} for t, r in monthly.iterrows()],
    }


def _setup(first_order, tp=100.0):
    global TP
    TP = tp
    dp.DEPOSIT = DEPOSIT
    sp.ENTRY = first_order
    sp.coin_cfg = coin_cfg


def _trades(coin):
    return sp.coin_trades((coin, [STEP]))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--first-order', type=float, required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--tp', type=float, default=100.0, help='тейк, %% от средней; 100 — без тейка')
    args = ap.parse_args()
    _setup(args.first_order, args.tp)
    with Pool(initializer=_setup, initargs=(args.first_order, args.tp)) as pool:
        data = {c: d[STEP] for c, d in pool.map(_trades, COINS)}
    trailing = {f'{c}USDT': round(dp.vol_unit(sp.load_15m(c)), 1) for c in COINS}
    result = report(args.first_order, data, trailing)
    pnl, taken, open_n = sp.portfolio(data, len(COINS), 'first')
    for name, a, b in (('IS', sp.START, dp.SPLIT), ('OOS', dp.SPLIT, sp.END), ('всё', sp.START, sp.END)):
        st = sp.stats(pnl, taken, open_n, a, b)
        print(f"{name:4s} {st['ann']:6.1f}%/год, DD от депозита {st['dd']:5.1f}%, худший месяц {st['m_worst']}%")
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({**result['metrics'], 'trailing': trailing,
                      'yearly': [y['return_pct'] for y in result['yearly']]}, ensure_ascii=False, indent=2))
