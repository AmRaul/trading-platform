import { usePriceStore } from '@/lib/store';
import type { Bot } from '@/lib/types';

export const STRADDLE_REASON: Record<string, string> = {
  TRAILING_STOP: 'трейлинг', TIME_STOP: 'стоп по времени', MAX_REARMS: 'лимит пил',
  MANUAL_CLOSE: 'вручную', EXCHANGE_CLOSED: 'закрыта на бирже',
};

// PnL стороны — как leg_pnl в domain/trading/straddle.py (ордера в USDT по своей цене)
function legPnl(orders: [number, number][], side: 'LONG' | 'SHORT', price: number) {
  const d = side === 'LONG' ? 1 : -1;
  return orders.reduce((a, [p, u]) => a + u * d * (price / p - 1), 0);
}

export default function StraddlePanel({ bot }: { bot: Bot }) {
  const livePrice = usePriceStore((s) => s.prices[bot.symbol]);
  const st = bot.straddle;
  if (!st) return null;
  const price = livePrice ?? st.price ?? st.anchor;
  const pnl = {
    LONG: legPnl(st.legs.LONG, 'LONG', price),
    SHORT: legPnl(st.legs.SHORT, 'SHORT', price),
  };
  const total = st.realized + pnl.LONG + pnl.SHORT;
  const money = (n: number) => `${n >= 0 ? '+' : ''}$${n.toFixed(2)}`;
  const tone = (n: number) => (n >= 0 ? 'text-green-400' : 'text-red-400');
  const phase = st.phase === 2
    ? `${st.working} · фаза 2 (минусовая закрыта, трейлинг)`
    : st.phase === 1
      ? `${st.working} добирает · ордеров ${st.working ? st.legs[st.working].length : 0}/${bot.config.order_count}`
      : st.reset_needed ? 'после пилы — жду возврата к точке' : 'пара открыта, жду хода';
  const step = bot.config.step_percent / 100;
  const leftMin = bot.config.time_stop_minutes && st.phase < 2
    ? Math.max(0, Math.round(bot.config.time_stop_minutes - (Date.now() / 1000 - st.started_at) / 60))
    : null;
  const leg = (side: 'LONG' | 'SHORT') => (
    <div>
      <span className="text-gray-500">{side} </span>
      {st.legs[side].length
        ? <span className={tone(pnl[side])}>{money(pnl[side])} <span className="text-gray-500">×{st.legs[side].length}</span></span>
        : <span className="text-gray-600">закрыт</span>}
    </div>
  );

  return (
    <div className="pt-2 border-t border-gray-700 mb-1 text-xs">
      <div className="flex justify-between mb-1">
        <span className="text-gray-500">Цена / точка</span>
        <span className="font-medium">${price.toFixed(4)} / ${st.anchor.toFixed(4)}</span>
      </div>
      <div className="text-purple-300 mb-1">{phase}</div>
      <div className="grid grid-cols-3 gap-x-2 mb-1">
        {leg('LONG')}
        {leg('SHORT')}
        <div className="text-right"><span className="text-gray-500">Итог </span><span className={`font-semibold ${tone(total)}`}>{money(total)}</span></div>
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
        <div className="flex justify-between">
          <span className="text-gray-500">Уровни</span>
          <span>↑{(st.anchor * (1 + step)).toFixed(4)} ↓{(st.anchor * (1 - step)).toFixed(4)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Стоп {st.working ?? ''}</span>
          <span className="text-red-400">{st.stop ? `$${st.stop.toFixed(4)}` : '—'}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Пилы</span>
          <span>{st.rearms}/{bot.config.max_rearms}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Стоп по врем.</span>
          <span>{leftMin != null ? `${leftMin} мин` : '—'}</span>
        </div>
      </div>
    </div>
  );
}
