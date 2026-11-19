"""
«Шорт альтов · пирамидинг»: что делать с позицией после полной сетки (4-го ордера).
Вход, доборы, стоп до 4-го ордера и трейлинг 1U — как в карточке (alt_short_pyramid_card.py);
меняется только выход, когда набраны все 4 ордера:

  base       — как сейчас: стоп avg+2%, трейлинг 1U
  tpX        — тейк X% от средней
  be         — стоп в безубыток (avg + 0.11% — покрыть комиссии входа/выхода)
  lockX      — стоп фиксирует X% прибыли от средней
  trailX     — трейлинг X% от цены (вместо 1U), только после 4-го ордера
  be_trailX  — безубыток + трейлинг X%

Запуск (из services/backtester, PYTHONPATH = backend:backtester:research):
    python research/alt_short_grid_exits.py base tp5 be trail3 ...
"""
import sys
from multiprocessing import Pool

import alt_short_pyramid_card as card
import donchian_pyramid as dp
import short_portfolio as sp
from app.domain.trading.position_calculator import PositionCalculator

FULL = 4
BE_BUFFER = 0.0011
VARIANT = 'base'


def parse(v):
    for kind in ('be_trail', 'trail', 'lock', 'tp'):
        if v.startswith(kind):
            return kind, float(v[len(kind):])
    return v, None


class GridExitCalc(PositionCalculator):
    """SHORT-калькулятор с другим выходом после полной сетки."""

    def calculate_stop_loss(self, side, orders, current_price, trailing_enabled=True):
        sl, kind_sl = super().calculate_stop_loss(side, orders, current_price, trailing_enabled)
        kind, x = parse(VARIANT)
        if len(orders) < FULL or kind in ('base', 'tp'):
            return sl, kind_sl
        avg = self.calculate_average_price(orders)
        cand = []
        if kind in ('be', 'be_trail'):
            cand.append(avg * (1 + BE_BUFFER))
        if kind == 'lock':
            cand.append(avg * (1 - x / 100))
        if kind in ('trail', 'be_trail'):
            cand.append(current_price * (1 + x / 100))
        return min([sl, *cand]), 'variant'

    def take_profit_price(self, side):
        kind, x = parse(VARIANT)
        if kind == 'tp' and len(self.orders) >= FULL:
            return self.calculate_average_price(self.orders) * (1 - x / 100)
        return super().take_profit_price(side)


def _setup(variant):
    global VARIANT
    VARIANT = variant
    card._setup(250.0)
    sp.PositionCalculator = GridExitCalc


def run(variant):
    _setup(variant)
    with Pool(initializer=_setup, initargs=(variant,)) as pool:
        data = {c: d[card.STEP] for c, d in pool.map(card._trades, card.COINS)}
    trailing = {f'{c}USDT': round(dp.vol_unit(sp.load_15m(c)), 1) for c in card.COINS}
    m = card.report(250.0, data, trailing)
    pnl, taken, open_n = sp.portfolio(data, len(card.COINS), 'first')
    row = {'variant': variant}
    for name, a, b in (('is', sp.START, dp.SPLIT), ('oos', dp.SPLIT, sp.END), ('all', sp.START, sp.END)):
        st = sp.stats(pnl, taken, open_n, a, b)
        row[f'{name}_ann'], row[f'{name}_dd'] = round(st['ann'], 1), round(st['dd'], 1)
        if name == 'all':
            row['m_worst'] = st['m_worst']
    mt = m['metrics']
    row.update(trades=mt['trades'], win=mt['win_rate_pct'], stops=mt['stops'], full=mt['full_grid_fills'],
               hours=mt['avg_trade_hours'], years=[y['return_pct'] for y in m['yearly']])
    return row


if __name__ == '__main__':
    print('variant      all%/г  DD%   IS%/г  OOS%/г OOS_DD  worstM  trades  win%  stops  full  hours  years')
    for v in sys.argv[1:] or ['base']:
        r = run(v)
        print(f"{r['variant']:11s} {r['all_ann']:6.1f} {r['all_dd']:5.1f} {r['is_ann']:6.1f} {r['oos_ann']:6.1f}"
              f" {r['oos_dd']:6.1f} {r['m_worst']:7} {r['trades']:6d} {r['win']:5.1f} {r['stops']:6d}"
              f" {r['full']:5d} {r['hours']:6.1f}  {r['years']}", flush=True)
