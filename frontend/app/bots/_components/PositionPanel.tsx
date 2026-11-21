import { usePriceStore, usePositionStore } from '@/lib/store';
import type { Bot } from '@/lib/types';

export default function PositionPanel({ bot }: { bot: Bot }) {
  const positionData = usePositionStore((s) => s.positions[bot.id]);
  const currentPrice = usePriceStore((s) => s.prices[bot.symbol]);

  if (!positionData) return null;

  const { average_price, current_sl, order_count, unrealized_pnl, last_order_price, total_size } = positionData;
  const maxOrders = bot.config.order_count;
  const stepPercent = bot.config.step_percent;
  const tpPercent = bot.config.tp_percent;

  const botType = bot.config.bot_type ?? 'pyramiding';
  // DCA: следующий страховочный — шаг от предыдущего ордера, × dca_multiplier_price
  // на каждом следующем уровне (mirrors PositionCalculator.next_dca_price)
  const dcaStep = (stepPercent / 100) * Math.pow(bot.config.dca_multiplier_price ?? 1, Math.max(order_count - 1, 0));
  const nextAvgPrice = last_order_price != null && average_price != null && order_count < maxOrders
    ? botType === 'dca'
      ? bot.side === 'LONG'
        ? last_order_price * (1 - dcaStep)
        : last_order_price * (1 + dcaStep)
      : bot.side === 'LONG'
        ? last_order_price * (1 + stepPercent / 100)
        : last_order_price * (1 - stepPercent / 100)
    : null;

  const tpTarget = average_price != null
    ? bot.side === 'LONG'
      ? average_price * (1 + tpPercent / 100)
      : average_price * (1 - tpPercent / 100)
    : null;

  // total_size is the position's notional value in USDT (not coin quantity),
  // so PnL scales with % price move applied to that notional — mirrors
  // calculate_unrealized_pnl in position_calculator.py.
  const livePnl = currentPrice && average_price && total_size
    ? bot.side === 'LONG'
      ? (total_size * (currentPrice - average_price)) / average_price
      : (total_size * (average_price - currentPrice)) / average_price
    : unrealized_pnl;

  const fmt = (n: number | null | undefined, digits = 2) =>
    n != null ? n.toFixed(digits) : '—';

  return (
    <div className="pt-2 border-t border-gray-700 mb-1">
      {currentPrice && (
        <div className="flex justify-between text-xs mb-1">
          <span className="text-gray-500">Цена</span>
          <span className="font-medium">${fmt(currentPrice, 4)}</span>
        </div>
      )}
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
        <div className="flex justify-between">
          <span className="text-gray-500">Avg</span>
          <span>${fmt(average_price, 4)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">SL</span>
          <span className="text-red-400">${fmt(current_sl, 4)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">{botType === 'dca' ? 'DCA↓' : 'Пир↑'}</span>
          <span>${fmt(nextAvgPrice, 4)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Орд</span>
          <span>{order_count}/{maxOrders}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">PnL</span>
          <span className={livePnl >= 0 ? 'text-green-400' : 'text-red-400'}>${fmt(livePnl, 2)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">TP</span>
          <span className="text-green-400">${fmt(tpTarget, 4)}</span>
        </div>
      </div>
    </div>
  );
}
