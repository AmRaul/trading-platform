"""
Пирамидинг от подтверждённого разворота:
  - контекст: MRC старшего ТФ (1h/4h) — одна из 3 последних закрытых свечей
    в зоне −2/−3 (для шорта +2/+3), т.е. цена у экстремума канала;
  - триггер: Supertrend(10, 3) младшего ТФ (15m/1h) развернулся в сторону сделки;
  - сопровождение: живой пирамидинг-бот (PositionCalculator), расстояния в
    единицах волатильности U = k × медианный дневной диапазон (как donchian_pyramid);
  - выход: стоп/трейлинг/тейк бота и, по варианту, сигнал MRC старшего ТФ:
      'mean'     — закрытие старшего ТФ по ту сторону средней линии канала,
      'opposite' — старший ТФ дошёл до противоположной зоны (+1..+3 / −1..−3).
Отбор — до SPLIT, одна конфигурация на все монеты; проверка — после SPLIT.

Запуск:
    python research/mrc_supertrend_pyramid.py --out /work/mrc_supertrend_pyramid.json
"""
import argparse
import itertools
import json
from multiprocessing import Pool

import numpy as np
import pandas as pd

import donchian_pyramid as dp
from indicators import TechnicalIndicators

COINS = dp.SELECT_COINS + ['XRP', 'WIF', 'BTC', 'ETH']
FUNDING_15M = 0.0001 / 32
TFS = [('15min', '1h'), ('15min', '4h'), ('1h', '4h')]
GRID = {
    'tfs': TFS,
    'exit': [None, 'mean', 'opposite'],
    'k': [0.5, 1.0],
    'order_count': [3, 4],
    'be2': [True, False],
    'tp_mult': [3, None],
}


def load_15m(coin):
    df = pd.read_csv(dp.DATA / f'{coin}USDT_15m_binance_futures.csv', parse_dates=['timestamp'])
    return df.sort_values('timestamp').drop_duplicates('timestamp').reset_index(drop=True)


def resample(df, tf):
    return df.resample(tf, on='timestamp').agg(
        {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()


def supertrend_dir(x, period=10, mult=3.0):
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
    trend[:period * 3] = 0
    return trend


def on_15m(values, index, tf, df):
    """Значения на закрытии свечей tf → по 15m барам (последнее закрытое на момент закрытия бара)."""
    src = pd.DataFrame({'t': index + pd.Timedelta(tf), 'v': values})
    bars = pd.DataFrame({'t': df['timestamp'] + pd.Timedelta('15min')})
    return pd.merge_asof(bars, src, on='t')['v'].values


def flips_on_15m(trend, index, tf, df):
    """Разворот Supertrend ровно на закрытии свечи tf → bool по 15m барам."""
    up = np.zeros(len(trend), bool); dn = np.zeros(len(trend), bool)
    up[1:] = (trend[1:] == 1) & (trend[:-1] == -1)
    dn[1:] = (trend[1:] == -1) & (trend[:-1] == 1)
    close_t = index + pd.Timedelta(tf)
    bar_close = (df['timestamp'] + pd.Timedelta('15min')).values
    pos = pd.Series(np.arange(len(df)), index=bar_close)
    res_up = np.zeros(len(df), bool); res_dn = np.zeros(len(df), bool)
    for arr, res in ((up, res_up), (dn, res_dn)):
        hit = pos.reindex(close_t[arr]).dropna().astype(int).values
        res[hit] = True
    return res_up, res_dn


def htf_series(df, htf):
    x = resample(df, htf).reset_index()
    m = TechnicalIndicators().calculate_mrc(x, length=200, inner_mult=1.0, outer_mult=2.415,
                                           gradsize=0.5, source='hlc3')
    rz = m['risk_zone'].values.astype(float)
    rz[:200] = 0
    zone_dn = pd.Series(np.isin(rz, [-2, -3]).astype(int)).rolling(3).max().fillna(0).values
    zone_up = pd.Series(np.isin(rz, [2, 3]).astype(int)).rolling(3).max().fillna(0).values
    above_mean = (x['close'] > m['meanline']).astype(float).values
    idx = x['timestamp']
    return {
        'ctx_long': on_15m(zone_dn, idx, htf, df) > 0,
        'ctx_short': on_15m(zone_up, idx, htf, df) > 0,
        'rz': on_15m(rz, idx, htf, df),
        'above_mean': on_15m(above_mean, idx, htf, df),
    }


def exit_signal(h, kind, side):
    if kind is None:
        return None
    if kind == 'mean':
        return (h['above_mean'] == 1) if side == 'LONG' else (h['above_mean'] == 0)
    rz = np.nan_to_num(h['rz'])
    return np.isin(rz, [1, 2, 3]) if side == 'LONG' else np.isin(rz, [-1, -2, -3])


def run_coin(coin):
    df = load_15m(coin)
    u_base = dp.vol_unit(df)
    end = df['timestamp'].iloc[-1] + pd.Timedelta('15min')
    htf_cache, flip_cache = {}, {}
    out = []
    for tfs, ex, k, oc, be2, tp_mult in itertools.product(*GRID.values()):
        ltf, htf = tfs
        if htf not in htf_cache:
            htf_cache[htf] = htf_series(df, htf)
        if ltf not in flip_cache:
            x = resample(df, ltf)
            flip_cache[ltf] = flips_on_15m(supertrend_dir(x), x.index, ltf, df)
        h = htf_cache[htf]
        flip_up, flip_dn = flip_cache[ltf]
        cfg = dp.bot_config(round(k * u_base, 2), oc, be2, tp_mult)
        for side, sig in (('LONG', flip_up & h['ctx_long']), ('SHORT', flip_dn & h['ctx_short'])):
            realized, floating, trades = dp.simulate(df, sig, cfg, side, FUNDING_15M, exit_signal(h, ex, side))
            out.append({'coin': coin, 'ltf': ltf, 'htf': htf, 'exit': ex or 'bot', 'k': k,
                        'order_count': oc, 'be2': be2, 'tp_mult': tp_mult or 0, 'side': side,
                        'is': dp.period_stats(df, realized, floating, trades, df['timestamp'].iloc[0], dp.SPLIT),
                        'oos': dp.period_stats(df, realized, floating, trades, dp.SPLIT, end)})
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    coins = [c for c in COINS if (dp.DATA / f'{c}USDT_15m_binance_futures.csv').exists()]
    with Pool() as pool:
        results = [r for rs in pool.map(run_coin, coins) for r in rs]
    with open(args.out, 'w') as f:
        json.dump(results, f, ensure_ascii=False, default=str)
    print(f'{len(results)} прогонов, монет {len(coins)}')
