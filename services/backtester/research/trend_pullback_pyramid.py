"""
Гипотеза: пирамидинг зарабатывает, когда вход стоит в начале продолжения
тренда. Вход — возобновление движения после отката внутри тренда старшего ТФ:

  ТВХ (LONG, SHORT — зеркально), всё по закрытым свечам:
    1. режим 4h: close > EMA200 и EMA50 > EMA200;
    2. откат 1h: за последние 6 закрытых 1h-свечей low касался EMA20 (или EMA50);
       'none' — контроль без условия отката;
    3. триггер 15m: 'brk' — close выше максимума 8 предыдущих свечей,
       'st' — разворот Supertrend(10, 3) вверх. Вход по закрытию 15m-свечи.

Сопровождение — живой пирамидинг-бот (PositionCalculator) через
donchian_pyramid.simulate, расстояния в единицах U = k × медианный дневной диапазон.
Отбор — до SPLIT, одна конфигурация на все монеты; проверка — после SPLIT.

Запуск:
    python research/trend_pullback_pyramid.py --out /work/trend_pullback_pyramid.json
"""
import argparse
import itertools
import json
from multiprocessing import Pool

import numpy as np
import pandas as pd

import donchian_pyramid as dp
from mrc_supertrend_pyramid import FUNDING_15M, load_15m, resample, supertrend_dir, on_15m, flips_on_15m

COINS = dp.SELECT_COINS + ['XRP', 'WIF', 'BTC', 'ETH']
PB_BARS = 6
BRK_BARS = 8
GRID = {
    'trigger': ['brk', 'st'],
    'pullback': ['ema20', 'ema50', 'none'],
    'k': [0.5, 1.0],
    'order_count': [3, 4],
    'be2': [True, False],
    'tp_mult': [3, None],
}


def ema(x, n):
    return x.ewm(span=n, adjust=False).mean()


def regime(df):
    x = resample(df, '4h')
    e50, e200 = ema(x['close'], 50), ema(x['close'], 200)
    up = ((x["close"] > e200) & (e50 > e200)).to_numpy(float, copy=True)
    dn = ((x["close"] < e200) & (e50 < e200)).to_numpy(float, copy=True)
    up[:200] = dn[:200] = 0
    return on_15m(up, x.index, '4h', df) == 1, on_15m(dn, x.index, '4h', df) == 1


def pullbacks(df):
    x = resample(df, '1h')
    out = {'none': (np.ones(len(df), bool), np.ones(len(df), bool))}
    for p in (20, 50):
        e = ema(x['close'], p)
        touch_dn = (x['low'] <= e).astype(int).rolling(PB_BARS).max().fillna(0).values
        touch_up = (x['high'] >= e).astype(int).rolling(PB_BARS).max().fillna(0).values
        out[f'ema{p}'] = (on_15m(touch_dn, x.index, '1h', df) == 1, on_15m(touch_up, x.index, '1h', df) == 1)
    return out


def triggers(df):
    hi = df['high'].rolling(BRK_BARS).max().shift(1)
    lo = df['low'].rolling(BRK_BARS).min().shift(1)
    x = resample(df, '15min')
    st_up, st_dn = flips_on_15m(supertrend_dir(x), x.index, '15min', df)
    return {
        'brk': ((df['close'] > hi).values, (df['close'] < lo).values),
        'st': (st_up, st_dn),
    }


def run_coin(coin):
    df = load_15m(coin)
    u_base = dp.vol_unit(df)
    end = df['timestamp'].iloc[-1] + pd.Timedelta('15min')
    reg_up, reg_dn = regime(df)
    pbs, trs = pullbacks(df), triggers(df)
    out = []
    for trig, pb, k, oc, be2, tp_mult in itertools.product(*GRID.values()):
        cfg = dp.bot_config(round(k * u_base, 2), oc, be2, tp_mult)
        sigs = {
            'LONG': reg_up & pbs[pb][0] & trs[trig][0],
            'SHORT': reg_dn & pbs[pb][1] & trs[trig][1],
        }
        for side, sig in sigs.items():
            realized, floating, trades = dp.simulate(df, sig, cfg, side, FUNDING_15M)
            out.append({'coin': coin, 'trigger': trig, 'pullback': pb, 'k': k, 'order_count': oc,
                        'be2': be2, 'tp_mult': tp_mult or 0, 'side': side, 'u': round(k * u_base, 2),
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
