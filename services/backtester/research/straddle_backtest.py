"""
Бэктест straddle («Мани Батон», TODO/6, реальная пара LONG+SHORT) на калькуляторе живого бота
(app.domain.trading.straddle.StraddleCalculator) — бот и бэктест считают одинаково.

Ручной выбор момента на истории не воспроизвести — проверяем механику на
моментах-заменителях и сравниваем со случайными:
  random  — случайный бар (не чаще раза в сутки на монету);
  volume  — объём за 1h ≥ VOL_Z сигм выше среднего за 7 дней, а диапазон за 4h
            ещё узкий (≤ RANGE_U · U) — «объём пошёл, движения ещё нет»;
  squeeze — диапазон за 8h ≤ SQUEEZE_U · U (сжатие волатильности).
Шаг и трейлинг — в долях U монеты (медианный дневной диапазон, считан до SPLIT).

Исполнение: вход/добор — по уровню при касании (гэп — по открытию) + проскальзывание,
стоп — по уровню (гэп — по открытию) − проскальзывание. Комиссия на каждый ордер
и выход, funding — на реальную позицию (лонг платит, шорт получает).
Результат сделки — в R = один шаг на первом ордере (X · step%).

Запуск (backend и research в PYTHONPATH):
    python research/straddle_backtest.py --out /tmp/straddle.json
"""
import argparse
import itertools
import json
from multiprocessing import Pool

import numpy as np
import pandas as pd

import donchian_pyramid as dp
import trend_pullback_pyramid as tpp
from app.domain.trading.straddle import ADD, CLOSE, OPEN, SIDES, StraddleAction, StraddleCalculator
from mrc_supertrend_pyramid import FUNDING_15M, load_15m

START, END = pd.Timestamp('2021-01-01'), pd.Timestamp('2026-10-02')
ENTRY = 100.0
SLIP = 0.0005
MIN_GAP_BARS = 96          # не чаще раза в сутки на монету
RANDOM_PER_COIN = 400
VOL_Z, RANGE_U, SQUEEZE_U = 2.5, 0.35, 0.2
MAX_BARS = 96 * 30         # страховка: сделка не дольше 30 дней

GRID = {
    'step_u': [0.1, 0.2, 0.3],
    'adds': [2, 3],
    'phase2': [2, 3],
    'add_stop': [0.5, 1.0],
    'trail_u': [0.5, 1.0],
    'time_h': [4, 24],
    'rearms': [0, 2],
}
CONFIGS = [dict(zip(GRID, v)) for v in itertools.product(*GRID.values())]


def bot_config(c, u):
    return {'entry_size_usdt': ENTRY, 'step_percent': c['step_u'] * u, 'order_count': c['adds'] + 1,
            'pyramiding_multiplier': 1.0, 'phase2_after_steps': c['phase2'],
            'add_stop_steps': c['add_stop'], 'trailing_percent': c['trail_u'] * u,
            'time_stop_minutes': c['time_h'] * 60, 'max_rearms': c['rearms']}


def spaced(idx, rng=None, n=None):
    """Оставляет моменты не чаще MIN_GAP_BARS (по порядку или случайно)."""
    if rng is not None:
        idx = np.sort(rng.choice(idx, min(n * 3, len(idx)), replace=False))
    out, last = [], -MIN_GAP_BARS
    for i in idx:
        if i - last >= MIN_GAP_BARS:
            out.append(int(i))
            last = i
    if rng is not None and len(out) > n:
        out = sorted(rng.choice(out, n, replace=False).tolist())
    return np.array(out, dtype=int)


def moments(df, u, rng):
    n = len(df)
    hi, lo, c, v = (df[k].to_numpy(float, copy=True) for k in ('high', 'low', 'close', 'volume'))
    vol1h = pd.Series(v).rolling(4).sum()
    base = vol1h.shift(4).rolling(96 * 7)
    z = ((vol1h - base.mean()) / base.std()).to_numpy()
    rng4 = ((pd.Series(hi).rolling(16).max() - pd.Series(lo).rolling(16).min()) / pd.Series(c) * 100).to_numpy()
    rng8 = ((pd.Series(hi).rolling(32).max() - pd.Series(lo).rolling(32).min()) / pd.Series(c) * 100).to_numpy()
    valid = np.arange(n) > 96 * 8
    return {
        'random': spaced(np.where(valid)[0], rng, RANDOM_PER_COIN),
        'volume': spaced(np.where(valid & (z >= VOL_Z) & (rng4 <= RANGE_U * u))[0]),
        'squeeze': spaced(np.where(valid & (rng8 <= SQUEEZE_U * u))[0]),
    }


def fill_level(calc, st, a):
    """Уровень, на котором сработало действие (исполнение по касанию); None — по рынку."""
    if a.kind == ADD:
        return calc.level(st.anchor, a.side, st.adds + 1)
    if a.kind == CLOSE:
        if a.reason == 'PHASE2':
            return calc.level(st.anchor, st.working, calc.phase2_steps)
        if a.reason in ('WHIPSAW', 'TRAILING_STOP'):
            return st.stop
    return None


def simulate(calc, o, h, l, c, ts, i):
    """Одна конструкция (реальная пара) от закрытия бара i.
    Возвращает (pnl USDT, фаза 2 была, перевзводов, баров)."""
    st = calc.start(c[i], ts[i])
    fees = funding = 0.0
    phase2 = False
    for j in range(i, min(len(c), i + MAX_BARS)):
        if j > i:
            for side in SIDES:
                funding += (1 if side == 'LONG' else -1) * sum(u for _, u in st.legs[side]) * FUNDING_15M
            path = (o[j], l[j], h[j], c[j]) if c[j] >= o[j] else (o[j], h[j], l[j], c[j])
        else:
            path = (c[i],)  # запуск — пара по close бара i
        for k, p in enumerate(path):
            calc.update_marks(st, p)
            while (a := calc.decide(st, p, ts[j])) is not None:
                lvl = fill_level(calc, st, a)
                fill = p if (k == 0 or lvl is None) else lvl
                sgn = 1 if a.side == 'LONG' else -1
                if a.kind in (OPEN, ADD):
                    fill *= 1 + sgn * SLIP
                    fees += a.usdt * dp.FEE
                elif a.kind == CLOSE:
                    fill *= 1 - sgn * SLIP
                    orders = st.legs[a.side]
                    fees += sum(u * fill / pr for pr, u in orders) * dp.FEE
                phase2 |= st.phase == 2
                calc.apply(st, a, fill, ts[j])
                if st.done:
                    for side in SIDES:  # завершение — закрыть остаток
                        if st.legs[side]:
                            fees += sum(u * p / pr for pr, u in st.legs[side]) * dp.FEE
                            calc.apply(st, StraddleAction(CLOSE, side, reason=st.exit_reason), p, ts[j])
                    return st.realized - fees - funding, phase2, st.rearms, j - i
    return st.total(c[-1]) - fees - funding, phase2, st.rearms, len(c) - i


def run_coin(coin):
    df = load_15m(coin)
    df = df[(df['timestamp'] >= START) & (df['timestamp'] < END)].reset_index(drop=True)
    u = dp.vol_unit(df)
    o, h, l, c = (df[k].to_numpy(float, copy=True) for k in ('open', 'high', 'low', 'close'))
    # секунды независимо от разрешения datetime (в pandas 3 — микросекунды)
    ts = df['timestamp'].to_numpy().astype('datetime64[s]').astype('int64')
    rng = np.random.default_rng(abs(hash(coin)) % 2**32)
    ms = moments(df, u, rng)
    out = {}
    for ci, cfg in enumerate(CONFIGS):
        calc = StraddleCalculator(bot_config(cfg, u))
        r_unit = ENTRY * cfg['step_u'] * u / 100
        for name, idx in ms.items():
            rows = [simulate(calc, o, h, l, c, ts, i) for i in idx]
            out[(ci, name)] = {
                't': ts[idx].tolist(),
                'r': [round(x[0] / r_unit, 3) for x in rows],
                'p2': [bool(x[1]) for x in rows],
                'bars': [int(x[3]) for x in rows],
            }
    return coin, round(u, 2), {k: len(v) for k, v in ms.items()}, out


def summary(rs):
    rs = np.asarray(rs)
    if not len(rs):
        return None
    wins, losses = rs[rs > 0], rs[rs <= 0]
    return {'n': int(len(rs)), 'avg_r': round(float(rs.mean()), 3),
            'win_pct': round(float((rs > 0).mean() * 100), 1),
            'avg_win': round(float(wins.mean()), 2) if len(wins) else 0,
            'avg_loss': round(float(losses.mean()), 2) if len(losses) else 0,
            'pf': round(float(wins.sum() / -losses.sum()), 2) if losses.sum() < 0 else None}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    coins = [x for x in tpp.COINS if (dp.DATA / f'{x}USDT_15m_binance_futures.csv').exists()]
    res = []
    with Pool(6, maxtasksperchild=1) as pool:
        for r in pool.imap_unordered(run_coin, coins):
            res.append(r)
            print(f'{len(res)}/{len(coins)} {r[0]} U={r[1]} моменты {r[2]}', flush=True)
    split = int(dp.SPLIT.timestamp())
    table = []
    for ci, cfg in enumerate(CONFIGS):
        for name in ('random', 'volume', 'squeeze'):
            r_is, r_oos, p2 = [], [], []
            for _, _, _, out in res:
                d = out[(ci, name)]
                for t, r, f in zip(d['t'], d['r'], d['p2']):
                    (r_is if t < split else r_oos).append(r)
                    p2.append(f)
            table.append({**cfg, 'moment': name, 'is': summary(r_is), 'oos': summary(r_oos),
                          'phase2_pct': round(float(np.mean(p2) * 100), 1) if p2 else 0})
    with open(args.out, 'w') as f:
        json.dump({'coins': {co: {'u': u, 'moments': m} for co, u, m, _ in res}, 'table': table}, f,
                  ensure_ascii=False)
    print(f'{len(CONFIGS)} конфигов × 3 типа моментов, монет {len(coins)}')
