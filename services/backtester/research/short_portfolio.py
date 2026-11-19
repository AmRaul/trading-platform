"""
Портфель шортов альтов на одном депозите (продолжение trend_pullback_pyramid).

Сигнал: режим 4h вниз (close < EMA200, EMA50 < EMA200) + разворот Supertrend 15m вниз.
Сопровождение — живой пирамидинг-бот (PositionCalculator), 3 ордера, без be2,
без тейка; стоп/трейлинг = 0.5U, шаг добора — варьируется:
    'u0.25', 'u0.5', 'u1'   — в единицах волатильности U монеты,
    'p1', 'p1.5', 'p2', 'p3' — фиксированный % для всех монет.

Портфель: не больше N позиций одновременно, одна позиция на монету.
Если сигналов больше свободных слотов — 'first' (по порядку) или 'weak'
(самые слабые к BTC за 7 дней). Для каждой монеты сделка просчитана от каждого
сигнала, поэтому пропущенный вход не сдвигает остальные.

Размер фиксированный: первый ордер = UNIT_PCT % депозита, без реинвеста.
DD — от пика в $ к депозиту, поэтому доходность и DD линейны по размеру,
и сравнение идёт по ratio = доходность в год / DD.

Запуск:
    python research/short_portfolio.py --out /work/short_portfolio.json
"""
import argparse
import itertools
import json
from multiprocessing import Pool

import numpy as np
import pandas as pd

import donchian_pyramid as dp
import trend_pullback_pyramid as tpp
from app.domain.trading.entities import OrderInfo
from app.domain.trading.position_calculator import PositionCalculator
from mrc_supertrend_pyramid import FUNDING_15M, load_15m

UNIT_PCT = 5.0
ENTRY = dp.DEPOSIT * UNIT_PCT / 100
STEPS = ['u0.25', 'u0.5', 'u1', 'p1', 'p1.5', 'p2', 'p3']
CAPS = [3, 5, 8, 99]
PICKS = ['first', 'weak']
REL_BARS = 7 * 96
START, END = pd.Timestamp('2021-01-01'), pd.Timestamp('2026-10-02')
GRID_IDX = pd.date_range(START, END, freq='15min')


def coin_cfg(df, step):
    u = dp.vol_unit(df)
    cfg = dp.bot_config(round(0.5 * u, 2), 3, False, None)
    cfg['entry_size_usdt'] = ENTRY
    cfg['step_percent'] = round(float(step[1:]) * u, 2) if step[0] == 'u' else float(step[1:])
    return cfg


def one_trade(df, i, cfg, side='SHORT'):
    """Одна сделка от сигнала на баре i — тот же цикл, что dp.simulate.
    Возвращает (бар выхода, pnl, число ордеров, плавающий pnl по барам i..выход-1)."""
    s = 1 if side == 'LONG' else -1
    o, h, l, c = df['open'].values, df['high'].values, df['low'].values, df['close'].values
    n = len(df)
    calc = PositionCalculator(cfg)
    calc.add_order(OrderInfo(1, c[i], cfg['entry_size_usdt']))
    sl, _ = calc.calculate_stop_loss(side, calc.orders, c[i])
    fees, funding = cfg['entry_size_usdt'] * dp.FEE, 0.0
    floating = [-fees]
    for j in range(i + 1, n):
        funding += s * calc.get_total_size() * FUNDING_15M
        path = [o[j], l[j], h[j], c[j]] if c[j] >= o[j] else [o[j], h[j], l[j], c[j]]
        exit_price = None
        for idx, p in enumerate(path):
            gap = idx == 0
            if calc.is_stop_loss_hit(side, p, sl):
                exit_price = p if gap else sl * (1 - s * dp.SL_SLIPPAGE)
                break
            tp = calc.take_profit_price(side)  # как в живом боте: тейк есть только у полной позиции
            if tp and (p - tp) * s >= 0:
                exit_price = p if gap else tp
                break
            added = False
            while calc.should_add_order(side, p, calc.get_last_order_price()):
                level = calc.get_last_order_price() * (1 + s * (cfg['step_percent'] / 100 - 0.0005))
                fill = p if gap else level
                size = calc.calculate_next_order_size()
                calc.add_order(OrderInfo(len(calc.orders) + 1, fill, size))
                fees += size * dp.FEE
                sl, _ = calc.calculate_stop_loss(side, calc.orders, fill)
                added = True
            if not added:
                new_sl, _ = calc.calculate_stop_loss(side, calc.orders, p)
                if sl == 0 or (new_sl - sl) * s > 0:
                    sl = new_sl
        avg, size = calc.calculate_average_price(calc.orders), calc.get_total_size()
        if exit_price is not None:
            fees += size * (exit_price / avg) * dp.FEE
            return j, s * size * (exit_price - avg) / avg - fees - funding, len(calc.orders), np.array(floating)
        floating.append(s * size * (c[j] - avg) / avg - fees - funding)
    return None


def rel_strength(df, btc):
    """Доходность монеты за 7 дней минус доходность BTC — по барам монеты."""
    r = df['close'].pct_change(REL_BARS)
    b = pd.merge_asof(df[['timestamp']], btc.assign(br=btc['close'].pct_change(REL_BARS))[['timestamp', 'br']],
                      on='timestamp')['br']
    return (r - b).values


def coin_trades(args):
    coin, steps = args
    df = load_15m(coin)
    df = df[(df['timestamp'] >= START) & (df['timestamp'] < END)].reset_index(drop=True)
    sig = tpp.regime(df)[1] & tpp.triggers(df)['st'][1]
    rel = rel_strength(df, load_15m('BTC'))
    gpos = GRID_IDX.get_indexer(df['timestamp'])
    out = {}
    for step in steps:
        cfg = coin_cfg(df, step)
        trades = []
        for i in np.where(sig)[0]:
            t = one_trade(df, i, cfg)
            if t and gpos[i] >= 0 and gpos[t[0]] >= 0:
                trades.append((int(gpos[i]), int(gpos[t[0]]), t[1], t[2],
                               0.0 if np.isnan(rel[i]) else float(rel[i]), t[3]))
        out[step] = trades
    return coin, out


def portfolio(by_coin, cap, pick):
    """by_coin: coin -> список сделок. Возвращает pnl по сетке GRID_IDX и принятые сделки."""
    entries = {}
    for coin, trades in by_coin.items():
        for t in trades:
            entries.setdefault(t[0], []).append((coin, t))
    pnl = np.zeros(len(GRID_IDX))
    busy_until, taken = {}, []
    open_n = np.zeros(len(GRID_IDX), int)
    for g in sorted(entries):
        cands = [(c, t) for c, t in entries[g] if busy_until.get(c, -1) < g]
        if pick == 'weak':
            cands.sort(key=lambda x: x[1][4])
        for coin, t in cands:
            active = sum(1 for e in busy_until.values() if e >= g)
            if active >= cap:
                break
            busy_until[coin] = t[1]
            taken.append((coin, t))
            fl = t[5]
            pnl[g:g + len(fl)] += fl
            pnl[t[1]:] += t[2]
            open_n[g:t[1]] += 1
    return pnl, taken, open_n


def stats(pnl, taken, open_n, a, b):
    m = (GRID_IDX >= a) & (GRID_IDX < b)
    eq = dp.DEPOSIT + pnl[m] - pnl[m][0]
    dd = float((np.maximum.accumulate(eq) - eq).max() / dp.DEPOSIT * 100)
    yrs = (b - a).days / 365.25
    ann = float((eq[-1] - eq[0]) / dp.DEPOSIT * 100 / yrs)
    months = pd.Series(eq, index=GRID_IDX[m]).resample('ME').last()
    mret = months.diff().dropna() / dp.DEPOSIT * 100
    tr = [t for _, t in taken if a <= GRID_IDX[t[1]] < b]
    return {'ann': round(ann, 1), 'dd': round(dd, 1), 'ratio': round(ann / max(dd, 0.1), 2),
            'm_pos': round(float((mret > 0).mean() * 100)), 'm_worst': round(float(mret.min()), 1),
            'trades': len(tr), 'full_grid': round(100 * np.mean([t[3] == 3 for t in tr]), 0) if tr else 0,
            'max_open': int(open_n[m].max())}


def yearly(pnl):
    y = pd.Series(pnl, index=GRID_IDX).resample('YE').last()
    return [int(v) for v in (y.diff().fillna(y) / dp.DEPOSIT * 100).round(0)]


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    coins = [c for c in tpp.COINS if (dp.DATA / f'{c}USDT_15m_binance_futures.csv').exists()]
    with Pool() as pool:
        data = dict(pool.map(coin_trades, [(c, STEPS) for c in coins]))
    results = []
    for step, cap, pick in itertools.product(STEPS, CAPS, PICKS):
        if cap == 99 and pick == 'weak':
            continue
        pnl, taken, open_n = portfolio({c: data[c][step] for c in coins}, cap, pick)
        results.append({'step': step, 'cap': cap, 'pick': pick,
                        'is': stats(pnl, taken, open_n, START, dp.SPLIT),
                        'oos': stats(pnl, taken, open_n, dp.SPLIT, END),
                        'years': yearly(pnl)})
    with open(args.out, 'w') as f:
        json.dump(results, f, ensure_ascii=False)
    print(f'{len(results)} портфелей, монет {len(coins)}')
