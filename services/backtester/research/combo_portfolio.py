"""
Портфель: MRC DCA BTC 15m Long + EMA200 1d  +  шорт-пирамида 5 альтов.
Обе стратегии считаются их же research-скриптами (комиссии taker 0.055%,
maker 0.02% на TP MRC, funding, плавающий PnL). Без реинвеста, PnL в $.
Сценарии издержек: base (как в скриптах) и x2 (все комиссии удвоены —
грубо закладывает проскальзывание ~0.05% на сторону).
"""
import json
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

RESEARCH = sys.argv[1]
sys.path.insert(0, RESEARCH)

import donchian_pyramid as dp  # noqa: E402
import short_portfolio as sp  # noqa: E402
import alt_short_pyramid_card as card  # noqa: E402
import mrc_dca_trend_long as mrc  # noqa: E402

MRC_DEP, MRC_FO = 5700.0, 280.0
SH_DEP, SH_FO = 5000.0, 250.0
BASE = dict(dp=dp.FEE, taker=mrc.FEE_TAKER, maker=mrc.FEE_MAKER)


def set_fees(mult):
    dp.FEE = BASE['dp'] * mult
    mrc.FEE_TAKER = BASE['taker'] * mult
    mrc.FEE_MAKER = BASE['maker'] * mult


def init(mult):
    card._setup(SH_FO)
    set_fees(mult)


def short_coin(coin):
    return card._trades(coin)


def mrc_pnl(mult):
    set_fees(mult)
    mrc.PARAMS['first_order'] = MRC_FO
    df, sig = mrc.load(str(dp.DATA / 'BTCUSDT_15m_binance_futures.csv'))
    realized, floating, trades = mrc.simulate(df, sig)
    s = pd.Series(realized + floating, index=df['timestamp'].values)
    s = s[~s.index.duplicated()].reindex(sp.GRID_IDX, method='ffill').fillna(0.0)
    return s.values - s.values[0], len(trades)


def short_pnl(mult):
    with Pool(initializer=init, initargs=(mult,)) as pool:
        data = {c: d[card.STEP] for c, d in pool.map(short_coin, card.COINS)}
    pnl, taken, _ = sp.portfolio(data, len(card.COINS), 'first')
    return pnl - pnl[0], len(taken)


def stats(pnl, dep, a=sp.START, b=sp.END):
    m = (sp.GRID_IDX >= a) & (sp.GRID_IDX < b)
    p = pnl[m] - pnl[m][0]
    eq = dep + p
    dd = float((np.maximum.accumulate(eq) - eq).max() / dep * 100)
    yrs = (b - a).days / 365.25
    ann = float(p[-1] / dep * 100 / yrs)
    mo = pd.Series(p, index=sp.GRID_IDX[m]).resample('ME').last()
    mret = mo.diff().fillna(mo) / dep * 100
    # самая долгая «подводная» серия (дней без нового максимума)
    peak = np.maximum.accumulate(eq)
    under = eq < peak - 1e-9
    longest, cur = 0, 0
    for u in under[::96]:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)
    return {'ann': round(ann, 1), 'dd': round(dd, 1), 'ratio': round(ann / max(dd, 0.1), 2),
            'm_pos': round(float((mret > 0).mean() * 100)), 'm_worst': round(float(mret.min()), 1),
            'm_avg': round(float(mret.mean()), 2), 'underwater_days': longest}


def yearly(pnl, dep):
    y = pd.Series(pnl, index=sp.GRID_IDX).resample('YE').last()
    return {int(k.year): round(float(v), 1) for k, v in (y.diff().fillna(y) / dep * 100).items()}


def monthly(pnl):
    mo = pd.Series(pnl, index=sp.GRID_IDX).resample('ME').last()
    return mo.diff().fillna(mo)


if __name__ == '__main__':
    out = {}
    for mult in (1.0, 2.0):
        m, m_tr = mrc_pnl(mult)
        s, s_tr = short_pnl(mult)
        tag = f'fees_x{mult:g}'
        res = {'trades': {'mrc': m_tr, 'short': s_tr}}
        for name, pnl, dep in (('mrc', m, MRC_DEP), ('short', s, SH_DEP)):
            res[name] = {'all': stats(pnl, dep), 'is': stats(pnl, dep, sp.START, dp.SPLIT),
                         'oos': stats(pnl, dep, dp.SPLIT, sp.END), 'years': yearly(pnl, dep)}
        # веса: шорт-часть масштабируется (больше/меньше первый ордер), депозит общий
        combos = {}
        for w in (0.5, 1.0, 1.5, 2.0):
            dep = MRC_DEP + SH_DEP
            pnl = m + w * s
            combos[f'short_x{w:g}'] = {'all': stats(pnl, dep), 'is': stats(pnl, dep, sp.START, dp.SPLIT),
                                       'oos': stats(pnl, dep, dp.SPLIT, sp.END), 'years': yearly(pnl, dep)}
        res['combo'] = combos
        mm, ms = monthly(m), monthly(s)
        res['corr_monthly'] = round(float(mm.corr(ms)), 2)
        both_neg = int(((mm < 0) & (ms < 0)).sum())
        res['months'] = {'total': len(mm), 'mrc_neg': int((mm < 0).sum()), 'short_neg': int((ms < 0).sum()),
                         'both_neg': both_neg}
        res['monthly'] = {str(k.date())[:7]: [round(float(a), 0), round(float(b), 0)]
                          for k, a, b in zip(mm.index, mm.values, ms.values)}
        out[tag] = res
        print(tag, json.dumps({k: v for k, v in res.items() if k != 'monthly'}, ensure_ascii=False, indent=1))
    with open(sys.argv[2], 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
