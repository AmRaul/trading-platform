"""
Исследование «MRC DCA BTC 15m Long + EMA200 1d» — источник цифр для карточки
готовой стратегии (backend/app/domain/ready_strategies/data/*.json).

Не использует движок backtester.py: там страховочные исполняются по close бара
(не больше одной за бар), а max_drawdown_percent / margin_call работают как
скрытые стопы. Здесь — лимитная сетка на 15m OHLC:
  - вход по close бара, где MRC risk_zone == -2 и close 1d > EMA200 (последняя
    закрытая дневная свеча);
  - страховочные по своей цене при касании low (гэп — по open);
  - путь внутри свечи: бычья O->L->H->C, медвежья O->H->L->C;
  - TP = avg * (1 + tp), аварийный SL = avg * (1 - sl) после заполнения всей сетки;
  - комиссии: taker 0.055% (вход, страховочные, стоп), maker 0.02% (TP);
  - funding 0.01% / 8ч на открытый объём.
Equity = депозит + реализованный + плавающий PnL, проверяется на каждом баре.

Запуск (из контейнера backtester-web, данные — services/backtester/data):
    python research/mrc_dca_trend_long.py --out /work/mrc_dca_btc_15m_long.json
    python research/mrc_dca_trend_long.py --first-order 560 --out /work/mrc_dca_btc_15m_long_aggressive.json
    (результат копируется в backend/app/domain/ready_strategies/data/)
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from indicators import TechnicalIndicators  # noqa: E402

PARAMS = {
    'symbol': 'BTCUSDT',
    'timeframe': '15m',
    'mrc': {'length': 200, 'inner_mult': 1.0, 'outer_mult': 2.415, 'gradsize': 0.5,
            'entry_band': 2, 'source': 'hlc3'},
    'trend_filter': {'timeframe': '1D', 'ema_period': 200},
    'safety_orders': 4,
    'step_percent': 1.55,
    'martingale': 2.0,
    'tp_percent': 0.97,
    'sl_percent': 20.0,
    'deposit': 5700.0,
    'first_order': 280.0,
}
FEE_TAKER, FEE_MAKER = 0.00055, 0.0002
FUNDING_PER_BAR = 0.0001 / 32


def load(csv_path):
    df = pd.read_csv(csv_path, parse_dates=['timestamp'])
    df = df.sort_values('timestamp').drop_duplicates('timestamp').reset_index(drop=True)
    m = PARAMS['mrc']
    rz = TechnicalIndicators().calculate_mrc(
        df, length=m['length'], inner_mult=m['inner_mult'], outer_mult=m['outer_mult'],
        gradsize=m['gradsize'], source=m['source'])['risk_zone'].values

    tf, period = PARAMS['trend_filter']['timeframe'], PARAMS['trend_filter']['ema_period']
    htf = df.resample(tf, on='timestamp').agg({'close': 'last'}).dropna()
    htf['ema'] = htf['close'].ewm(span=period, adjust=False).mean()
    htf['avail'] = htf.index + pd.Timedelta(tf)  # свеча доступна только после закрытия
    bars = pd.DataFrame({'t': df['timestamp'] + pd.Timedelta('15min')})
    trend = pd.merge_asof(bars, htf[['avail', 'close', 'ema']].rename(columns={'avail': 't'}), on='t')

    signal = (rz == -m['entry_band']) & (trend['close'] > trend['ema']).values
    signal[:m['length'] + 1] = False
    return df, signal


def simulate(df, signal):
    p = PARAMS
    n_so, step, mart = p['safety_orders'], p['step_percent'] / 100, p['martingale']
    tp_pct, sl_pct, unit = p['tp_percent'] / 100, p['sl_percent'] / 100, p['first_order']
    o, h, l, c = (df[k].values for k in ('open', 'high', 'low', 'close'))
    ts = df['timestamp'].values
    n = len(df)
    realized, floating = np.zeros(n), np.zeros(n)
    trades, cum, i = [], 0.0, 0
    while i < n:
        realized[i] = cum
        if not signal[i]:
            i += 1
            continue
        entry = c[i]
        sizes = [unit * mart ** k for k in range(n_so + 1)]
        prices = [entry * (1 - step) ** k for k in range(n_so + 1)]
        notionals, qtys = [sizes[0]], [sizes[0] / entry]
        fees, funding, exit_price, reason = sizes[0] * FEE_TAKER, 0.0, None, None
        j = i + 1
        while j < n and reason is None:
            funding += sum(notionals) * FUNDING_PER_BAR
            path = [o[j], l[j], h[j], c[j]] if c[j] >= o[j] else [o[j], h[j], l[j], c[j]]
            for a, b in zip(path[:-1], path[1:]):
                if reason:
                    break
                if b < a:
                    while len(qtys) < n_so + 1 and b <= prices[len(qtys)]:
                        k = len(qtys)
                        fill = min(prices[k], a)
                        notionals.append(sizes[k])
                        qtys.append(sizes[k] / fill)
                        fees += sizes[k] * FEE_TAKER
                    if len(qtys) == n_so + 1:
                        sl = sum(notionals) / sum(qtys) * (1 - sl_pct)
                        if b <= sl:
                            exit_price, reason = min(sl, a), 'stop'
                            fees += exit_price * sum(qtys) * FEE_TAKER
                else:
                    tp = sum(notionals) / sum(qtys) * (1 + tp_pct)
                    if b >= tp:
                        exit_price, reason = max(tp, a), 'tp'
                        fees += exit_price * sum(qtys) * FEE_MAKER
            qty = sum(qtys)
            avg = sum(notionals) / qty
            if reason is None:
                floating[j] = (c[j] - avg) * qty - fees - funding
            else:
                pnl = (exit_price - avg) * qty - fees - funding
                cum += pnl
                trades.append({'entry_time': pd.Timestamp(ts[i]), 'exit_time': pd.Timestamp(ts[j]),
                               'orders': len(qtys), 'reason': reason, 'pnl': pnl})
            realized[j] = cum
            j += 1
        i = j
    return realized, floating, pd.DataFrame(trades)


def report(df, realized, floating, trades):
    dep = PARAMS['deposit']
    ts = df['timestamp']
    equity = dep + realized + floating
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / peak * 100

    def pct_between(a, b):
        ia = int(np.searchsorted(ts.values, np.datetime64(a)))
        ib = min(int(np.searchsorted(ts.values, np.datetime64(b))), len(ts)) - 1
        return round((realized[ib] - realized[ia]) / dep * 100, 1)

    years = sorted(ts.dt.year.unique())
    yearly = [{'year': int(y), 'return_pct': pct_between(f'{y}-01-01', f'{y + 1}-01-01')} for y in years]

    monthly = pd.DataFrame({'t': ts, 'equity': equity, 'dd': dd}).set_index('t').resample('ME').last()
    span_years = (ts.iloc[-1] - ts.iloc[0]).days / 365.25
    total = realized[-1] / dep * 100
    full_grid = int((trades['orders'] == PARAMS['safety_orders'] + 1).sum())
    durations = (trades['exit_time'] - trades['entry_time']).dt.total_seconds() / 3600

    return {
        'params': PARAMS,
        'period': {'start': str(ts.iloc[0].date()), 'end': str(ts.iloc[-1].date())},
        'metrics': {
            'total_return_pct': round(total, 1),
            'avg_annual_return_pct': round(total / span_years, 1),
            'max_drawdown_pct': round(float(dd.max()), 1),
            'trades': int(len(trades)),
            'win_rate_pct': round(float((trades['pnl'] > 0).mean() * 100), 1),
            'stops': int((trades['reason'] == 'stop').sum()),
            'full_grid_fills': full_grid,
            'avg_trade_hours': round(float(durations.mean()), 1),
            'max_trade_days': round(float(durations.max() / 24), 1),
            'liquidations': int((equity <= 0).sum() > 0),
            'period_2021_2023_pct': pct_between('2021-01-01', '2024-01-01'),
            'period_2024_2026_pct': pct_between('2024-01-01', str(ts.iloc[-1].date())),
        },
        'yearly': yearly,
        'equity_curve': [{'date': str(t.date()), 'equity': round(float(r.equity), 2),
                          'drawdown_pct': round(float(r.dd), 2)} for t, r in monthly.iterrows()],
    }


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=str(Path(__file__).resolve().parent.parent / 'data' / 'BTCUSDT_15m_binance_futures.csv'))
    ap.add_argument('--out', required=True)
    ap.add_argument('--first-order', type=float, default=PARAMS['first_order'],
                    help='размер первого ордера, USDT (депозит фиксирован — PARAMS["deposit"])')
    args = ap.parse_args()
    PARAMS['first_order'] = args.first_order
    df, signal = load(args.data)
    result = report(df, *simulate(df, signal))
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result['metrics'], ensure_ascii=False, indent=2))
