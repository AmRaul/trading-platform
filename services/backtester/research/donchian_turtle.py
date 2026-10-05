"""
Диагностика к donchian_pyramid.py: есть ли преимущество у самого ВХОДА по
пробою Donchian, если убрать механику пирамидинг-бота.

Классические «черепахи», без доборов и тейка:
  - LONG: закрытие свечи tf выше максимума n предыдущих свечей и дневка выше EMA200;
    SHORT: закрытие ниже минимума n предыдущих и дневка ниже EMA200;
  - выход: закрытие свечи tf ниже минимума (для шорта — выше максимума) n/2 предыдущих;
  - защитный стоп: 2 × ATR(20) свечей tf от входа, проверяется внутри 1h свечей;
  - размер: риск 1% депозита на сделку (объём = 1% / расстояние до стопа), не больше 3 депозитов.
Исполнение, комиссии, funding, периоды отбора/проверки — как в donchian_pyramid.py.

Запуск:
    python research/donchian_turtle.py --out /work/donchian_turtle.json
"""
import argparse
import itertools
import json
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

import donchian_pyramid as dp

RISK_PCT = 1.0
MAX_NOTIONAL = 3.0  # × депозит
COINS = dp.SELECT_COINS + ['XRP', 'WIF', 'BTC', 'ETH']
GRID = {'tf': ['1h', '4h', '1D'], 'n': [20, 55], 'side': ['LONG', 'SHORT']}


def tf_levels(df, tf, n):
    """Уровни на закрытии каждой свечи tf, привязанные к 1h бару с тем же закрытием."""
    x = df.resample(tf, on='timestamp').agg({'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
    prev_close = x['close'].shift(1)
    tr = pd.concat([x.high - x.low, (x.high - prev_close).abs(), (x.low - prev_close).abs()], axis=1).max(axis=1)
    x['atr'] = tr.rolling(20).mean()
    x['up_entry'] = x['high'].rolling(n).max().shift(1)
    x['dn_entry'] = x['low'].rolling(n).min().shift(1)
    x['up_exit'] = x['high'].rolling(n // 2).max().shift(1)
    x['dn_exit'] = x['low'].rolling(n // 2).min().shift(1)
    x.index = x.index + pd.Timedelta(tf)  # время закрытия свечи tf
    bar_close = df['timestamp'] + pd.Timedelta('1h')
    return x.reindex(bar_close.values)  # NaN там, где свеча tf не закрывается


def trend(df):
    d = dp.daily(df)
    d['ema'] = d['close'].ewm(span=200, adjust=False).mean()
    d = d.iloc[200:]
    d['avail'] = d.index + pd.Timedelta('1D')
    bar_close = df['timestamp'] + pd.Timedelta('1h')
    m = pd.merge_asof(pd.DataFrame({'t': bar_close}),
                      d[['avail', 'close', 'ema']].rename(columns={'avail': 't'}), on='t')
    return (m['close'] > m['ema']).values, (m['close'] < m['ema']).values


def simulate(df, lv, up, dn, side):
    o, h, l, c = (df[k].values for k in ('open', 'high', 'low', 'close'))
    ts = df['timestamp'].values
    tf_close = lv['close'].notna().values
    tfc = lv['close'].values
    atr, up_e, dn_e, up_x, dn_x = (lv[k].values for k in ('atr', 'up_entry', 'dn_entry', 'up_exit', 'dn_exit'))
    s = 1 if side == 'LONG' else -1
    n = len(df)
    realized, floating = np.zeros(n), np.zeros(n)
    trades, cum, i = [], 0.0, 0
    while i < n:
        realized[i] = cum
        entry_ok = tf_close[i] and not np.isnan(atr[i]) and (
            (s == 1 and up[i] and tfc[i] > up_e[i]) or (s == -1 and dn[i] and tfc[i] < dn_e[i]))
        if not entry_ok:
            i += 1
            continue
        entry = c[i]
        stop = entry - s * 2 * atr[i]
        notional = min(dp.DEPOSIT * RISK_PCT / 100 / (2 * atr[i] / entry), MAX_NOTIONAL * dp.DEPOSIT)
        fees, funding, exit_price, reason = notional * dp.FEE, 0.0, None, None
        j = i + 1
        while j < n and reason is None:
            funding += s * notional * dp.FUNDING_PER_BAR  # лонг платит, шорт получает
            if (s == 1 and l[j] <= stop) or (s == -1 and h[j] >= stop):
                gap = (s == 1 and o[j] <= stop) or (s == -1 and o[j] >= stop)
                exit_price, reason = (o[j] if gap else stop), 'stop'
            elif tf_close[j] and ((s == 1 and tfc[j] < dn_x[j]) or (s == -1 and tfc[j] > up_x[j])):
                exit_price, reason = c[j], 'channel'
            if reason is None:
                floating[j] = s * notional * (c[j] - entry) / entry - fees - funding
            else:
                fees += notional * exit_price / entry * dp.FEE
                pnl = s * notional * (exit_price - entry) / entry - fees - funding
                cum += pnl
                trades.append((pd.Timestamp(ts[i]), pd.Timestamp(ts[j]), 1, reason, pnl))
            realized[j] = cum
            j += 1
        i = j
    return realized, floating, trades


def run_coin(coin):
    df = dp.load_1h(coin)
    up, dn = trend(df)
    end = df['timestamp'].iloc[-1] + pd.Timedelta('1h')
    out = []
    for tf, n, side in itertools.product(*GRID.values()):
        realized, floating, trades = simulate(df, tf_levels(df, tf, n), up, dn, side)
        stats = {per: dp.period_stats(df, realized, floating, trades, a, b)
                 for per, a, b in (('is', df['timestamp'].iloc[0], dp.SPLIT), ('oos', dp.SPLIT, end))}
        if side == 'SHORT':  # для шорта «купить и держать» неинформативно — показываем падение цены
            for st in stats.values():
                if st:
                    st['bh'] = -st['bh']
        out.append({'coin': coin, 'tf': tf, 'n': n, 'side': side, **stats})
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    coins = [c for c in COINS if (dp.DATA / f'{c}USDT_1h_binance_futures.csv').exists()
             or (dp.DATA / f'{c}USDT_15m_binance_futures.csv').exists()]
    with Pool() as pool:
        results = [r for rs in pool.map(run_coin, coins) for r in rs]
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str))
    print(f'{len(results)} прогонов, монет {len(coins)}')
