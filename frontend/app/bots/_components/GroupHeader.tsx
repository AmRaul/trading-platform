import { ChevronDown, ChevronRight } from 'lucide-react';
import { BotGroup, money } from './grouping';

export default function GroupHeader({ group, collapsed, onToggle }: { group: BotGroup; collapsed: boolean; onToggle: () => void }) {
  const open = group.bots.filter((b) => b.state === 'PYRAMIDING' || b.state === 'STRADDLE').length;
  const realized = group.bots.reduce((sum, b) => sum + (b.total_pnl ?? 0), 0);
  const unrealized = group.bots.reduce((sum, b) => sum + (b.open_position?.unrealized_pnl ?? 0), 0);
  const tone = (n: number) => (n >= 0 ? 'text-green-400' : 'text-red-400');
  return (
    <button onClick={onToggle} className="w-full flex items-center gap-2 mb-2 text-left">
      {collapsed ? <ChevronRight size={16} className="shrink-0 text-gray-500" /> : <ChevronDown size={16} className="shrink-0 text-gray-500" />}
      <span className="font-semibold text-sm text-gray-200 truncate">{group.key}</span>
      <span className="shrink-0 px-1.5 rounded text-xs bg-gray-800 text-gray-400">{group.bots.length}</span>
      {open > 0 && <span className="shrink-0 text-xs text-green-400" title="В позиции">● {open}</span>}
      <span className="flex-1 border-t border-gray-800 mx-1" />
      {open > 0 && (
        <span className={`shrink-0 text-xs ${tone(unrealized)}`} title="Текущий PnL открытых позиций">
          {money(unrealized)} откр.
        </span>
      )}
      <span className={`shrink-0 text-xs font-medium ${tone(realized)}`} title="Реализованный PnL">
        {money(realized)}
      </span>
    </button>
  );
}
