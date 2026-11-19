import type { EntrySignal } from '@/lib/types';

// Параметры MRC по умолчанию совпадают с бэктестом стратегии MRC DCA (length 200, outer 2.415, hlc3)
const DEFAULT_ENTRY_SIGNAL: EntrySignal = {
  type: 'mrc',
  timeframe: '15',
  entry_band: 2,
  trend_ema_period: 200,
  trend_timeframe: 'D',
};

const TF_LABEL: Record<string, string> = { '60': '1h', '240': '4h', D: 'дневке' };

export function signalName(s: EntrySignal | null | undefined) {
  return s?.type === 'supertrend' ? `Supertrend ${s.timeframe}m` : 'MRC';
}

export function trendLabel(s: EntrySignal | null | undefined) {
  if (!s?.trend_ema_period) return '';
  const fast = s.trend_ema_fast ? `EMA${s.trend_ema_fast}/` : 'EMA';
  return ` · ${fast}${s.trend_ema_period} ${TF_LABEL[s.trend_timeframe] ?? s.trend_timeframe}`;
}

export default function EntrySignalFields({
  value,
  onChange,
}: {
  value: EntrySignal | null;
  onChange: (v: EntrySignal | null) => void;
}) {
  return (
    <div className="col-span-2 border-t border-gray-700 pt-2">
      <label className="flex items-center gap-1.5 cursor-pointer text-xs">
        <input
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked ? { ...DEFAULT_ENTRY_SIGNAL } : null)}
        />
        {value?.type === 'supertrend'
          ? `Вход по развороту ${signalName(value)}${trendLabel(value)}`
          : 'Вход по сигналу MRC (15m, полоса 2)'}
      </label>
      {value && (
        <div className="flex items-center gap-2 mt-2 text-xs">
          <span className="text-gray-400">
            Фильтр тренда EMA на {TF_LABEL[value.trend_timeframe] ?? value.trend_timeframe}
          </span>
          <input
            type="number"
            min={2}
            max={500}
            placeholder="выкл"
            value={value.trend_ema_period ?? ''}
            onChange={(e) =>
              onChange({ ...value, trend_ema_period: e.target.value ? parseInt(e.target.value) : null })
            }
            className="w-20 px-2 py-1 bg-gray-700 border border-gray-600 rounded"
          />
        </div>
      )}
    </div>
  );
}
