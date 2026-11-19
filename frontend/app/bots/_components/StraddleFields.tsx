export interface StraddleValues {
  phase2_after_steps: number;
  add_stop_steps: number;
  time_stop_minutes: number | null;
  max_rearms: number;
}

export const STRADDLE_DEFAULTS: StraddleValues = {
  phase2_after_steps: 3,
  add_stop_steps: 1,
  time_stop_minutes: 240,
  max_rearms: 1,
};

// Переключение формы на straddle: шаг/доборы/трейлинг — как в примере TODO/6
export function toStraddle<T extends object>(f: T): T {
  return {
    ...f, bot_type: 'straddle', side: 'NEUTRAL', order_count: 4, step_percent: 2,
    pyramiding_multiplier: 1, use_trailing: true, trailing_percent: 5, tp_percent: 100,
    entry_signal: null,
  };
}

export default function StraddleFields({ value, onChange }: {
  value: StraddleValues;
  onChange: (v: Partial<StraddleValues>) => void;
}) {
  const num = (k: keyof StraddleValues, parse: (x: string) => number) => (e: React.ChangeEvent<HTMLInputElement>) =>
    onChange({ [k]: e.target.value === '' ? null : parse(e.target.value) });
  const input = 'w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded';
  return (
    <>
      <div>
        <label className="block text-xs text-gray-400 mb-1">Фаза 2 через (шагов)</label>
        <input type="number" value={value.phase2_after_steps} onChange={num('phase2_after_steps', parseInt)}
          className={input} min="1" max="10" />
        <p className="text-[11px] text-gray-500 mt-1">Закрыть минусовую сторону и вести весь ход трейлингом</p>
      </div>
      <div>
        <label className="block text-xs text-gray-400 mb-1">Стоп доборов (шагов от 1-го)</label>
        <input type="number" value={value.add_stop_steps} onChange={num('add_stop_steps', parseFloat)}
          className={input} step="0.5" min="0.5" max="3" />
        <p className="text-[11px] text-gray-500 mt-1">1 — в точке запуска, 0.5 — полшага до неё, 1.5 — за ней</p>
      </div>
      <div>
        <label className="block text-xs text-gray-400 mb-1">Стоп по времени (мин)</label>
        <input type="number" value={value.time_stop_minutes ?? ''} onChange={num('time_stop_minutes', parseInt)}
          className={input} min="1" placeholder="без лимита" />
        <p className="text-[11px] text-gray-500 mt-1">Нет фазы 2 за это время — закрыть всё</p>
      </div>
      <div>
        <label className="block text-xs text-gray-400 mb-1">Перевзводов после пилы</label>
        <input type="number" value={value.max_rearms} onChange={num('max_rearms', parseInt)}
          className={input} min="0" max="10" />
        <p className="text-[11px] text-gray-500 mt-1">Сколько раз можно вернуться в точку запуска</p>
      </div>
    </>
  );
}
