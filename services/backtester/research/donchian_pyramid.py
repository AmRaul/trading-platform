"""
Исследование: пробой Donchian + пирамидинг живого бота, только LONG,
фильтр тренда — дневная свеча выше EMA200.

Стопы, доборы и тейк считает PositionCalculator из backend
(backend/app/domain/trading/position_calculator.py) — тот же код, что у живого
бота, поэтому исследование и бот не могут разойтись по логике сопровождения.
Порядок проверок на каждой точке цены повторяет StrategyEngine.on_price_update:
стоп → тейк → добор → подтяжка стопа (только вверх для LONG).

Все расстояния — в «единицах волатильности» монеты U = k × медианный дневной
диапазон (high-low)/close на периоде отбора: шаг добора = U, начальный стоп = U,
стоп с 3-го ордера = U, трейлинг = U, тейк на последнем ордере = 3U (или без тейка).

Исполнение — на 1h свечах (путь внутри свечи: бычья O→L→H→C, медвежья O→H→L→C),
комиссия 0.055% на каждый ордер и выход, funding 0.01% / 8ч.
Отбор параметров — только на периоде до SPLIT, одна конфигурация на все монеты;
период после SPLIT смотрится один раз для выбранной конфигурации.

Запуск (контейнер backtester-web, backend смонтирован в /backend):
    python research/donchian_pyramid.py --out /work/donchian_pyramid.json
"""
import argparse
import itertools
import json
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/backend')
from app.domain.trading.entities import OrderInfo  # noqa: E402
from app.domain.trading.position_calculator import PositionCalculator  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / 'data'
SPLIT = pd.Timestamp('2024-07-01')
DEPOSIT = 5700.0
UNIT_PCT = 25.0          # объём первого ордера, % депозита
FEE = 0.00055
FUNDING_PER_BAR = 0.0001 / 8
SL_SLIPPAGE = 0.0005     # PositionCalculator.is_stop_loss_hit slippage_pct=0.05

# Монеты для отбора параметров (волатильные), контрольные и «невиданные»
SELECT_COINS = ['SOL', 'AVAX', 'LINK', 'DOGE', 'NEAR', 'INJ', '1000PEPE', 'SUI',
                'APT', 'ARB', 'OP', 'FET', 'TIA']
EXTRA_COINS = ['WIF', 'BTC', 'ETH']   # WIF — нет истории до SPLIT, BTC/ETH — для сравнения

GRID = {
    'tf': ['1h', '4h'],
    'n': [20, 55],
    'k': [0.5, 1.0, 1.5],
    'order_count': [3, 4],
    'be2': [True, False],
    'tp_mult': [3, None],   # None — без тейка, выход только по трейлингу/стопу
}


def load_1h(coin):
    f1h = DATA / f'{coin}USDT_1h_binance_futures.csv'
    f15 = DATA / f'{coin}USDT_15m_binance_futures.csv'
    df = pd.read_csv(f1h if f1h.exists() else f15, parse_dates=['timestamp'])
    df = df.sort_values('timestamp').drop_duplicates('timestamp')
    if not f1h.exists():
        df = df.resample('1h', on='timestamp').agg(
            {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna().reset_index()
    return df.reset_index(drop=True)


def daily(df):
    return df.resample('1D', on='timestamp').agg({'high': 'max', 'low': 'min', 'close': 'last'}).dropna()


def vol_unit(df):
    """Медианный дневной диапазон, % — на периоде отбора (или первых 180 днях)."""
    d = daily(df)
    sample = d[d.index < SPLIT]
    if len(sample) < 180:
        sample = d.iloc[:180]
    return float(((sample.high - sample.low) / sample.close).median() * 100)


def signals(df, tf, n):
    """bool по 1h барам: на закрытии этого бара закрылась свеча tf с пробоем
    максимума n предыдущих свечей tf, и последняя закрытая дневка выше EMA200."""
    x = df.resample(tf, on='timestamp').agg({'high': 'max', 'close': 'last'}).dropna()
    upper = x['high'].rolling(n).max().shift(1)
    brk = x[x['close'] > upper]
    close_times = set(brk.index + pd.Timedelta(tf))

    d = daily(df)
    d['ema'] = d['close'].ewm(span=200, adjust=False).mean()
    d = d.iloc[200:]
    d['avail'] = d.index + pd.Timedelta('1D')
    bar_close = df['timestamp'] + pd.Timedelta('1h')
    m = pd.merge_asof(pd.DataFrame({'t': bar_close}),
                      d[['avail', 'close', 'ema']].rename(columns={'avail': 't'}), on='t')
    trend_up = (m['close'] > m['ema']).fillna(False).values
    return bar_close.isin(close_times).values & trend_up


def bot_config(u, order_count, be2, tp_mult=3):
    return {
        'bot_type': 'pyramiding',
        'order_count': order_count,
        'entry_size_usdt': DEPOSIT * UNIT_PCT / 100,
        'step_percent': u,
        'pyramiding_multiplier': 1.0,
        'sl_initial': u,
        'sl_breakeven_on_order2': be2,
        'sl_breakeven_plus': 0.25 * u,
        'sl_after_order3': u,
        'use_trailing': True,
        'trailing_percent': u,
        # без тейка: тейк так далеко, что не достигается, позицию ведёт трейлинг
        'tp_percent': tp_mult * u if tp_mult else 100.0,
    }


def simulate(df, sig, cfg, side='LONG', funding_per_bar=FUNDING_PER_BAR, exit_sig=None):
    """Сопровождение позиции кодом живого бота. side — LONG/SHORT;
    exit_sig — bool по барам: закрыть позицию на закрытии бара (выход по сигналу)."""
    s = 1 if side == 'LONG' else -1
    o, h, l, c = (df[k].values for k in ('open', 'high', 'low', 'close'))
    ts = df['timestamp'].values
    n = len(df)
    realized, floating = np.zeros(n), np.zeros(n)
    trades, cum, i = [], 0.0, 0
    while i < n:
        realized[i] = cum
        if not sig[i]:
            i += 1
            continue
        calc = PositionCalculator(cfg)
        calc.add_order(OrderInfo(1, c[i], cfg['entry_size_usdt']))
        sl, _ = calc.calculate_stop_loss(side, calc.orders, c[i])
        fees, funding, exit_price, reason = cfg['entry_size_usdt'] * FEE, 0.0, None, None
        j = i + 1
        while j < n and reason is None:
            funding += s * calc.get_total_size() * funding_per_bar  # лонг платит, шорт получает
            path = [o[j], l[j], h[j], c[j]] if c[j] >= o[j] else [o[j], h[j], l[j], c[j]]
            for idx, p in enumerate(path):
                gap = idx == 0  # открытие свечи — уровень мог быть перепрыгнут гэпом
                if calc.is_stop_loss_hit(side, p, sl):
                    trigger = sl * (1 - s * SL_SLIPPAGE)
                    exit_price, reason = (p if gap else trigger), 'stop'
                    break
                if calc.is_take_profit_hit(side, p):
                    tp = calc.take_profit_price(side)
                    exit_price, reason = (p if gap else tp), 'tp'
                    break
                added = False
                while calc.should_add_order(side, p, calc.get_last_order_price()):
                    level = calc.get_last_order_price() * (1 + s * (cfg['step_percent'] / 100 - 0.0005))
                    fill = p if gap else level
                    size = calc.calculate_next_order_size()
                    calc.add_order(OrderInfo(len(calc.orders) + 1, fill, size))
                    fees += size * FEE
                    sl, _ = calc.calculate_stop_loss(side, calc.orders, fill)
                    added = True
                if not added:
                    new_sl, _ = calc.calculate_stop_loss(side, calc.orders, p)
                    if sl == 0 or (new_sl - sl) * s > 0:
                        sl = new_sl
            if reason is None and exit_sig is not None and exit_sig[j]:
                exit_price, reason = c[j], 'signal'
            avg, size = calc.calculate_average_price(calc.orders), calc.get_total_size()
            if reason is None:
                floating[j] = s * size * (c[j] - avg) / avg - fees - funding
            else:
                fees += size * (exit_price / avg) * FEE
                pnl = s * size * (exit_price - avg) / avg - fees - funding
                cum += pnl
                trades.append((pd.Timestamp(ts[i]), pd.Timestamp(ts[j]), len(calc.orders), reason, pnl))
            realized[j] = cum
            j += 1
        i = j
    return realized, floating, trades


def period_stats(df, realized, floating, trades, start, end):
    t = df['timestamp']
    mask = ((t >= start) & (t < end)).values
    if mask.sum() < 24 * 60:
        return None
    idx = np.where(mask)[0]
    eq = DEPOSIT + realized[idx] + floating[idx]
    eq = eq - realized[idx[0]]  # период начинается с депозита
    peak = np.maximum.accumulate(eq)
    dd = float(((peak - eq) / peak).max() * 100)
    ret = float((realized[idx[-1]] - realized[idx[0]]) / DEPOSIT * 100)
    years = (t.iloc[idx[-1]] - t.iloc[idx[0]]).days / 365.25
    tr = [x for x in trades if start <= x[1] < end]
    closes = df['close'].values[idx]
    bh = float((closes[-1] / closes[0] - 1) * 100)
    return {
        'ret': round(ret, 1), 'ann': round(ret / years, 1), 'dd': round(dd, 1),
        'ratio': round(ret / years / max(dd, 0.1), 2), 'trades': len(tr),
        'win': round(100 * np.mean([x[4] > 0 for x in tr]), 0) if tr else 0,
        'avg_orders': round(float(np.mean([x[2] for x in tr])), 2) if tr else 0,
        'liq': bool((eq <= 0).any()), 'bh': round(bh, 0), 'years': round(years, 1),
    }


def run_coin(args):
    coin, combos = args
    df = load_1h(coin)
    u_base = vol_unit(df)
    out = []
    sig_cache = {}
    for combo in combos:
        tf, n, k, oc, be2, tp_mult = combo
        if (tf, n) not in sig_cache:
            sig_cache[(tf, n)] = signals(df, tf, n)
        realized, floating, trades = simulate(df, sig_cache[(tf, n)], bot_config(round(k * u_base, 2), oc, be2, tp_mult))
        end = df['timestamp'].iloc[-1] + pd.Timedelta('1h')
        out.append({'coin': coin, 'tf': tf, 'n': n, 'k': k, 'order_count': oc, 'be2': be2, 'tp_mult': tp_mult,
                    'u': round(k * u_base, 2),
                    'is': period_stats(df, realized, floating, trades, df['timestamp'].iloc[0], SPLIT),
                    'oos': period_stats(df, realized, floating, trades, SPLIT, end)})
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    combos = list(itertools.product(*GRID.values()))
    coins = [c for c in SELECT_COINS + EXTRA_COINS
             if (DATA / f'{c}USDT_1h_binance_futures.csv').exists()
             or (DATA / f'{c}USDT_15m_binance_futures.csv').exists()]
    with Pool() as pool:
        results = [r for rs in pool.map(run_coin, [(c, combos) for c in coins]) for r in rs]
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str))
    print(f'{len(results)} прогонов, монет {len(coins)}, конфигураций {len(combos)}')
