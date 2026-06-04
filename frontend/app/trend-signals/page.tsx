'use client';

import { useQuery } from '@tanstack/react-query';
import { trendSignalsApi } from '@/lib/api';
import Navbar from '@/components/Navbar';
import { TrendingUp, TrendingDown } from 'lucide-react';

interface TrendSignal {
  id: number;
  symbol: string;
  side: string;
  entry_price: number;
  entry_time: string;
  ema21_4h: number;
  ema21_1h: number;
  trend_4h: string;
  pullback_1h: boolean;
  trigger_15m: boolean;
  stop_price: number;
  stop_pct: number;
  exit_price: number | null;
  exit_time: string | null;
  exit_reason: string | null;
  pnl_pct: number | null;
  duration_hrs: number | null;
  peak_pnl_pct: number | null;
  pyramid_count: number;
  status: string;
}

function PnlCell({ pnl }: { pnl: number | null }) {
  if (pnl === null) return <span className="text-gray-500">—</span>;
  return (
    <span className={`font-semibold ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
      {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}%
    </span>
  );
}

function formatPrice(p: number | null): string {
  if (p === null) return '—';
  if (p < 0.001) return p.toFixed(6);
  if (p < 0.1) return p.toFixed(5);
  if (p < 1) return p.toFixed(4);
  if (p < 100) return p.toFixed(3);
  return p.toFixed(2);
}

function StatusBadge({ signal }: { signal: TrendSignal }) {
  if (signal.status === 'OPEN') {
    return <span className="px-2 py-1 rounded text-xs bg-yellow-900 text-yellow-400">Открыт</span>;
  }
  if (signal.exit_reason === 'STOP') {
    return <span className="px-2 py-1 rounded text-xs bg-red-950 text-red-400">Стоп</span>;
  }
  if (signal.exit_reason === 'EMA_EXIT') {
    const positive = (signal.pnl_pct ?? 0) >= 0;
    return (
      <span className={`px-2 py-1 rounded text-xs ${positive ? 'bg-green-900 text-green-300' : 'bg-gray-700 text-gray-300'}`}>
        EMA выход
      </span>
    );
  }
  return <span className="px-2 py-1 rounded text-xs bg-gray-700 text-gray-300">Закрыт</span>;
}

export default function TrendSignalsPage() {
  const { data: signals = [], isLoading } = useQuery({
    queryKey: ['trend-signals'],
    queryFn: async () => (await trendSignalsApi.getAll()).data,
    refetchInterval: 5 * 60 * 1000,
  });

  const open = signals.filter((s: TrendSignal) => s.status === 'OPEN');
  const closed = signals.filter((s: TrendSignal) => s.status === 'CLOSED');
  const wins = closed.filter((s: TrendSignal) => (s.pnl_pct ?? 0) > 0);
  const winRate = closed.length ? ((wins.length / closed.length) * 100).toFixed(0) + '%' : '—';
  const avgPnl = closed.length
    ? (closed.reduce((acc: number, s: TrendSignal) => acc + (s.pnl_pct ?? 0), 0) / closed.length).toFixed(2)
    : null;
  const avgDuration = closed.filter((s: TrendSignal) => s.duration_hrs).length
    ? (closed.reduce((acc: number, s: TrendSignal) => acc + (s.duration_hrs ?? 0), 0) / closed.filter((s: TrendSignal) => s.duration_hrs).length).toFixed(1)
    : null;

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="mb-6">
          <h1 className="text-3xl font-bold">Trend Signals</h1>
          <p className="text-gray-400 text-sm mt-1">4H/1H/15m — SOL, AVAX, LINK и другие ликвидные альты</p>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <p className="text-gray-400 text-sm">Всего / Открытых</p>
            <p className="text-2xl font-bold mt-1">
              {signals.length} <span className="text-gray-500 font-normal text-lg">/</span>{' '}
              <span className="text-yellow-400 text-lg">{open.length}</span>
            </p>
          </div>
          <div className="bg-gray-800 rounded-lg p-4 border border-blue-900 border-2">
            <p className="text-blue-400 text-sm">Win rate</p>
            <p className="text-2xl font-bold mt-1 text-blue-300">{winRate}</p>
            <p className="text-gray-500 text-xs mt-1">{closed.length} завершено</p>
          </div>
          <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <p className="text-gray-400 text-sm">Avg PnL</p>
            <p className={`text-2xl font-bold mt-1 ${avgPnl !== null ? (parseFloat(avgPnl) >= 0 ? 'text-green-400' : 'text-red-400') : 'text-gray-500'}`}>
              {avgPnl !== null ? `${parseFloat(avgPnl) >= 0 ? '+' : ''}${avgPnl}%` : '—'}
            </p>
          </div>
          <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <p className="text-gray-400 text-sm">Avg Duration</p>
            <p className="text-2xl font-bold mt-1 text-gray-300">
              {avgDuration !== null ? `${avgDuration}h` : '—'}
            </p>
          </div>
        </div>

        {/* Table */}
        <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-700 text-gray-300 uppercase text-xs">
                <tr>
                  <th className="text-left py-3 px-3">Symbol</th>
                  <th className="text-left py-3 px-3">Side</th>
                  <th className="text-right py-3 px-3">Entry</th>
                  <th className="text-right py-3 px-3">Stop%</th>
                  <th className="text-left py-3 px-3">Trend 4H</th>
                  <th className="text-right py-3 px-3">EMA21 1H</th>
                  <th className="text-right py-3 px-3">Peak PnL</th>
                  <th className="text-right py-3 px-3">Exit PnL</th>
                  <th className="text-right py-3 px-3">Duration</th>
                  <th className="text-left py-3 px-3">Exit</th>
                  <th className="text-left py-3 px-3">Status</th>
                  <th className="text-left py-3 px-3">Time</th>
                </tr>
              </thead>
              <tbody>
                {isLoading && (
                  <tr>
                    <td colSpan={12} className="text-center py-12 text-gray-400">Loading...</td>
                  </tr>
                )}
                {!isLoading && signals.length === 0 && (
                  <tr>
                    <td colSpan={12} className="text-center py-12 text-gray-400">
                      Сигналов пока нет — появятся после следующего скана (каждые 15 мин)
                    </td>
                  </tr>
                )}
                {signals.map((s: TrendSignal) => (
                  <tr key={s.id} className="border-t border-gray-700 hover:bg-gray-750">
                    <td className="py-3 px-3 font-semibold">{s.symbol.replace('USDT', '')}</td>
                    <td className="py-3 px-3">
                      {s.side === 'LONG'
                        ? <span className="flex items-center gap-1 text-green-400"><TrendingUp size={14} /> LONG</span>
                        : <span className="flex items-center gap-1 text-red-400"><TrendingDown size={14} /> SHORT</span>
                      }
                    </td>
                    <td className="py-3 px-3 text-right text-gray-300">${formatPrice(s.entry_price)}</td>
                    <td className="py-3 px-3 text-right text-red-400">{s.stop_pct?.toFixed(1)}%</td>
                    <td className="py-3 px-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        s.trend_4h === 'UP' ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'
                      }`}>
                        {s.trend_4h}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-right text-gray-400 text-xs">{formatPrice(s.ema21_1h)}</td>
                    <td className="py-3 px-3 text-right"><PnlCell pnl={s.peak_pnl_pct} /></td>
                    <td className="py-3 px-3 text-right"><PnlCell pnl={s.pnl_pct} /></td>
                    <td className="py-3 px-3 text-right text-gray-400">
                      {s.duration_hrs !== null ? `${s.duration_hrs}h` : '—'}
                    </td>
                    <td className="py-3 px-3 text-gray-400 text-xs">
                      {s.exit_reason ?? '—'}
                    </td>
                    <td className="py-3 px-3"><StatusBadge signal={s} /></td>
                    <td className="py-3 px-3 text-gray-400 text-xs">
                      {new Date(s.entry_time).toLocaleString('ru', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
