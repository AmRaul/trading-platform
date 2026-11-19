"""
Идея: MRC на старшем ТФ (1h/4h) показывает зону перепроданности («пора
разворачиваться»), Supertrend на младшем ТФ (15m/1h) подтверждает разворот —
только тогда запускается DCA-сетка MRC DCA (4 страховочных, шаг 1.55%, ×2,
TP 0.97%, стоп 20% после полной сетки).

Вход LONG на закрытии свечи младшего ТФ, если:
  - Supertrend(10, 3) младшего ТФ развернулся вверх на этой свече;
  - хотя бы одна из последних 3 закрытых свечей старшего ТФ была в зоне MRC
    −2 или −3 (вторая полоса или дальше);
  - опционально: дневка выше EMA200.
Сравнение с базой — текущим входом (MRC 15m, полоса −2, EMA200 1d).
Сетка и исполнение — simulate() из mrc_dca_trend_long.py, на 15m свечах.

Запуск:
    python research/mrc_supertrend_dca.py --out /work/mrc_supertrend_dca.json
"""
import argparse
import itertools
import json
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

import mrc_dca_trend_long as base
from indicators import TechnicalIndicators

DATA = Path(__file__).resolve().parent.parent / 'data'
COINS = ['BTC', 'ETH', 'SOL', 'AVAX', 'LINK', 'DOGE', 'BNB']
SPLIT = pd.Timestamp('2024-07-01')
GRID = {'ltf': ['15min', '1h'], 'htf': ['1h', '4h'], 'ema': [True, False]}


def resample(df, tf):
    return df.resample(tf, on='timestamp').agg(
        {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()


def supertrend_flip_up(x, period=10, mult=3.0):
    """bool по свечам x: Supertrend развернулся вверх на закрытии свечи."""
    h, l, c = x['high'].values, x['low'].values, x['close'].values
    prev_c = np.roll(c, 1); prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(abs(h - prev_c), abs(l - prev_c)))
    atr = pd.Series(tr).ewm(alpha=1 / period, adjust=False).mean().values
    hl2 = (h + l) / 2
    up, dn = hl2 - mult * atr, hl2 + mult * atr
    fu, fd = up.copy(), dn.copy()
    trend = np.ones(len(c), dtype=int)
    for i in range(1, len(c)):
        fu[i] = max(up[i], fu[i - 1]) if c[i - 1] > fu[i - 1] else up[i]
        fd[i] = min(dn[i], fd[i - 1]) if c[i - 1] < fd[i - 1] else dn[i]
        if trend[i - 1] == -1 and c[i] > fd[i - 1]:
            trend[i] = 1
        elif trend[i - 1] == 1 and c[i] < fu[i - 1]:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]
    flip = np.zeros(len(c), dtype=bool)
    flip[1:] = (trend[1:] == 1) & (trend[:-1] == -1)
    flip[:period * 3] = False
    return pd.Series(flip, index=x.index)


def at_bar_close(series, tf, df):
    """Значение на закрытии свечи tf → bool по 15m барам с тем же закрытием."""
    s = series.copy()
    s.index = s.index + pd.Timedelta(tf)
    bar_close = df['timestamp'] + pd.Timedelta('15min')
    return s.reindex(bar_close.values).fillna(False).values.astype(bool)


def htf_oversold_ctx(df, htf):
    """bool по 15m барам: одна из 3 последних закрытых свечей htf в зоне MRC −2/−3."""
    x = resample(df, htf).reset_index()
    rz = TechnicalIndicators().calculate_mrc(x, length=200, inner_mult=1.0, outer_mult=2.415,
                                            gradsize=0.5, source='hlc3')['risk_zone']
    zone = rz.isin([-2, -3]).astype(int).rolling(3).max().fillna(0).astype(bool)
    zone[:200] = False
    ctx = pd.DataFrame({'t': x['timestamp'] + pd.Timedelta(htf), 'z': zone.values})
    bar_close = pd.DataFrame({'t': df['timestamp'] + pd.Timedelta('15min')})
    m = pd.merge_asof(bar_close, ctx, on='t')
    return m['z'].fillna(False).values.astype(bool)


def ema_ok(df):
    d = resample(df, '1D')
    d['ema'] = d['close'].ewm(span=200, adjust=False).mean()
    d = d.iloc[200:]
    d['avail'] = d.index + pd.Timedelta('1D')
    bar_close = pd.DataFrame({'t': df['timestamp'] + pd.Timedelta('15min')})
    m = pd.merge_asof(bar_close, d[['avail', 'close', 'ema']].rename(columns={'avail': 't'}), on='t')
    return (m['close'] > m['ema']).values


def stats(df, realized, floating, trades, start, end):
    t = df['timestamp']
    idx = np.where(((t >= start) & (t < end)).values)[0]
    eq = base.PARAMS['deposit'] + realized[idx] + floating[idx] - realized[idx[0]]
    peak = np.maximum.accumulate(eq)
    dd = float(((peak - eq) / peak).max() * 100)
    ret = float((realized[idx[-1]] - realized[idx[0]]) / base.PARAMS['deposit'] * 100)
    years = (t.iloc[idx[-1]] - t.iloc[idx[0]]).days / 365.25
    tr = trades[(trades.exit_time >= start) & (trades.exit_time < end)] if len(trades) else trades
    full = tr[tr.orders == base.PARAMS['safety_orders'] + 1] if len(tr) else tr
    full_tp = full[full.reason == 'tp'] if len(full) else full
    months = years * 12
    return {
        'ann': round(ret / years, 1), 'dd': round(dd, 1), 'ratio': round(ret / years / max(dd, .1), 2),
        'trades': int(len(tr)), 'stops': int((tr.reason == 'stop').sum()) if len(tr) else 0,
        'full_grid_per_month': round(len(full) / months, 2),
        'full_grid_tp_pct': round(float(full_tp.pnl.mean()) / base.PARAMS['deposit'] * 100, 2) if len(full_tp) else None,
        'liq': bool((eq <= 0).any()),
    }


def run_coin(coin):
    df = pd.read_csv(DATA / f'{coin}USDT_15m_binance_futures.csv', parse_dates=['timestamp'])
    df = df.sort_values('timestamp').drop_duplicates('timestamp').reset_index(drop=True)
    end = df['timestamp'].iloc[-1] + pd.Timedelta('15min')
    trend = ema_ok(df)
    variants = {}
    # база — текущий вход стратегии
    _, base_sig = base.load(DATA / f'{coin}USDT_15m_binance_futures.csv')
    variants[('base MRC15m', '-', True)] = base_sig
    ctx_cache = {}
    for ltf, htf, ema in itertools.product(*GRID.values()):
        if pd.Timedelta(ltf) >= pd.Timedelta(htf):
            continue
        if htf not in ctx_cache:
            ctx_cache[htf] = htf_oversold_ctx(df, htf)
        flip = at_bar_close(supertrend_flip_up(resample(df, ltf)), ltf, df)
        sig = flip & ctx_cache[htf]
        if ema:
            sig = sig & trend
        variants[(f'ST {ltf}', f'MRC {htf}', ema)] = sig
    out = []
    for (ltf, htf, ema), sig in variants.items():
        realized, floating, trades = base.simulate(df, sig)
        out.append({'coin': coin, 'entry': ltf, 'context': htf, 'ema200': ema,
                    'is': stats(df, realized, floating, trades, df['timestamp'].iloc[0], SPLIT),
                    'oos': stats(df, realized, floating, trades, SPLIT, end)})
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    with Pool() as pool:
        results = [r for rs in pool.map(run_coin, COINS) for r in rs]
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str))
    print(f'{len(results)} прогонов')
