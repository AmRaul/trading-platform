'use client';

import { useQuery } from '@tanstack/react-query';
import { signalsApi } from '@/lib/api';
import Navbar from '@/components/Navbar';
import { TrendingUp, TrendingDown } from 'lucide-react';

interface Signal {
  id: number;
  symbol: string;
  side: string;
  strategy: string;
  entry_price: number;
  entry_time: string;
  vol_1h_pct: number;
  price_range_pct: number;
  avg_candle_size_pct: number;
  price_change_24h_pct: number;
  funding_rate: number;
  open_interest: number;
  price_15m: number | null;
  price_30m: number | null;
  price_60m: number | null;
  pnl_15m: number | null;
  pnl_30m: number | null;
  pnl_60m: number | null;
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

function formatPrice(p: number): string {
  if (p < 0.001) return p.toFixed(6);
  if (p < 0.1) return p.toFixed(5);
  if (p < 1) return p.toFixed(4);
  if (p < 100) return p.toFixed(3);
  return p.toFixed(2);
}

function formatVolume(v: number): string {
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(1)}B`;
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  return `$${(v / 1_000).toFixed(0)}K`;
}

export default function SignalsPage() {
  const { data: signals = [], isLoading } = useQuery({
    queryKey: ['signals'],
    queryFn: async () => (await signalsApi.getAll()).data,
    refetchInterval: 5 * 60 * 1000,
  });

  const filled = signals.filter((s: Signal) => s.status === 'FILLED');
  const pending = signals.filter((s: Signal) => s.status === 'PENDING');

  const winRate = (subset: Signal[]) => {
    const f = subset.filter(s => s.status === 'FILLED');
    if (!f.length) return '—';
    return (f.filter(s => (s.pnl_60m ?? 0) > 0).length / f.length * 100).toFixed(0) + '%';
  };

  const momentum = signals.filter((s: Signal) => (s.strategy ?? 'MOMENTUM') === 'MOMENTUM');
  const reversal = signals.filter((s: Signal) => s.strategy === 'REVERSAL');
  const breakout = signals.filter((s: Signal) => s.strategy === 'BREAKOUT');

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <Navbar />

      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-3xl font-bold">Signal Log</h1>
            <p className="text-gray-400 text-sm mt-1">Бэктест логики входа — без реальных ордеров</p>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <p className="text-gray-400 text-sm">Всего / В процессе</p>
            <p className="text-2xl font-bold mt-1">{signals.length} <span className="text-gray-500 font-normal text-lg">/</span> <span className="text-yellow-400 text-lg">{pending.length}</span></p>
          </div>
          <div className="bg-gray-800 rounded-lg p-4 border border-blue-900 border-2">
            <p className="text-blue-400 text-sm">MOMENTUM win rate</p>
            <p className="text-2xl font-bold mt-1 text-blue-300">{winRate(momentum)}</p>
            <p className="text-gray-500 text-xs mt-1">{momentum.filter(s => s.status === 'FILLED').length} завершено</p>
          </div>
          <div className="bg-gray-800 rounded-lg p-4 border border-purple-900 border-2">
            <p className="text-purple-400 text-sm">REVERSAL win rate</p>
            <p className="text-2xl font-bold mt-1 text-purple-300">{winRate(reversal)}</p>
            <p className="text-gray-500 text-xs mt-1">{reversal.filter(s => s.status === 'FILLED').length} завершено</p>
          </div>
          <div className="bg-gray-800 rounded-lg p-4 border border-green-900 border-2">
            <p className="text-green-400 text-sm">BREAKOUT win rate</p>
            <p className="text-2xl font-bold mt-1 text-green-300">{winRate(breakout)}</p>
            <p className="text-gray-500 text-xs mt-1">{breakout.filter(s => s.status === 'FILLED').length} завершено</p>
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
                  <th className="text-left py-3 px-3">Strategy</th>
                  <th className="text-right py-3 px-3">Entry</th>
                  <th className="text-right py-3 px-3">Vol 1h</th>
                  <th className="text-right py-3 px-3">Range</th>
                  <th className="text-right py-3 px-3">Volat.</th>
                  <th className="text-right py-3 px-3">24h %</th>
                  <th className="text-right py-3 px-3">PnL 15m</th>
                  <th className="text-right py-3 px-3">PnL 30m</th>
                  <th className="text-right py-3 px-3">PnL 60m</th>
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
                      Сигналов пока нет — они появятся после следующего скана скринера
                    </td>
                  </tr>
                )}
                {signals.map((s: Signal) => (
                  <tr key={s.id} className="border-t border-gray-700 hover:bg-gray-750">
                    <td className="py-3 px-3 font-semibold">{s.symbol.replace('USDT', '')}</td>
                    <td className="py-3 px-3">
                      {s.side === 'LONG'
                        ? <span className="flex items-center gap-1 text-green-400"><TrendingUp size={14} /> LONG</span>
                        : <span className="flex items-center gap-1 text-red-400"><TrendingDown size={14} /> SHORT</span>
                      }
                    </td>
                    <td className="py-3 px-3">
                      <span className={`px-2 py-1 rounded text-xs font-medium ${
                        s.strategy === 'MOMENTUM' ? 'bg-blue-900 text-blue-300' :
                        s.strategy === 'REVERSAL' ? 'bg-purple-900 text-purple-300' :
                        'bg-green-900 text-green-300'
                      }`}>
                        {s.strategy}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-right text-gray-300">${formatPrice(s.entry_price)}</td>
                    <td className="py-3 px-3 text-right">
                      <span className={s.vol_1h_pct >= 20 ? 'text-yellow-400 font-semibold' : 'text-orange-400 font-semibold'}>
                        {s.vol_1h_pct.toFixed(1)}%
                      </span>
                    </td>
                    <td className="py-3 px-3 text-right text-gray-300">{s.price_range_pct.toFixed(0)}%</td>
                    <td className="py-3 px-3 text-right text-gray-300">{s.avg_candle_size_pct.toFixed(2)}%</td>
                    <td className="py-3 px-3 text-right">
                      <span className={s.price_change_24h_pct >= 0 ? 'text-green-400' : 'text-red-400'}>
                        {s.price_change_24h_pct >= 0 ? '+' : ''}{s.price_change_24h_pct.toFixed(1)}%
                      </span>
                    </td>
                    <td className="py-3 px-3 text-right"><PnlCell pnl={s.pnl_15m} /></td>
                    <td className="py-3 px-3 text-right"><PnlCell pnl={s.pnl_30m} /></td>
                    <td className="py-3 px-3 text-right"><PnlCell pnl={s.pnl_60m} /></td>
                    <td className="py-3 px-3">
                      {(() => {
                        const isStopped = s.status === 'FILLED'
                          && s.pnl_15m !== null && s.pnl_30m !== null && s.pnl_60m !== null
                          && s.pnl_15m === s.pnl_30m && s.pnl_30m === s.pnl_60m
                          && s.pnl_60m <= -3.5;
                        return (
                          <span className={`px-2 py-1 rounded text-xs ${
                            isStopped ? 'bg-red-950 text-red-400' :
                            s.status === 'FILLED' ? 'bg-gray-700 text-gray-300' :
                            'bg-yellow-900 text-yellow-400'
                          }`}>
                            {isStopped ? 'Стоп' : s.status === 'FILLED' ? 'Готово' : 'В процессе'}
                          </span>
                        );
                      })()}
                    </td>
                    <td className="py-3 px-3 text-gray-400 text-xs">
                      {new Date(s.entry_time).toLocaleTimeString()}
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
