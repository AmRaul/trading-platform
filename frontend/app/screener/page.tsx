'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { screenerApi } from '@/lib/api';
import Navbar from '@/components/Navbar';
import { TrendingUp, TrendingDown, Minus, RefreshCw } from 'lucide-react';

interface Candidate {
  symbol: string;
  avg_candle_size_pct: number;
  volume_24h: number;
  volume_1h: number;
  funding_rate: number;
  price_change_24h_pct: number;
  high_24h: number;
  low_24h: number;
  open_interest: number;
  direction: string;
  price_range_pct: number | null;
  last_price: number;
}

function DirectionBadge({ direction }: { direction: string }) {
  if (direction === 'LONG') return (
    <span className="flex items-center gap-1 text-green-400">
      <TrendingUp size={14} /> UP
    </span>
  );
  if (direction === 'SHORT') return (
    <span className="flex items-center gap-1 text-red-400">
      <TrendingDown size={14} /> DOWN
    </span>
  );
  return (
    <span className="flex items-center gap-1 text-gray-400">
      <Minus size={14} /> FLAT
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
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
}

// Vol 1h ratio: сколько процентов дневного объёма прошло за последний час
// Средний час = 1/24 = 4.17%, если ratio >> 4% — аномалия
function volRatio(vol1h: number, vol24h: number): number | null {
  if (!vol24h) return null;
  return (vol1h / vol24h) * 100;
}

export default function ScreenerPage() {
  const queryClient = useQueryClient();
  const [isScanning, setIsScanning] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ['screener-latest'],
    queryFn: async () => (await screenerApi.getLatest()).data,
    refetchInterval: 15 * 60 * 1000,
  });

  const scanMutation = useMutation({
    mutationFn: () => screenerApi.triggerScan(),
    onMutate: () => setIsScanning(true),
    onSuccess: (res) => {
      queryClient.setQueryData(['screener-latest'], res.data);
      setIsScanning(false);
    },
    onError: () => setIsScanning(false),
  });

  const candidates: Candidate[] = data?.candidates ?? [];
  const scannedAt = data?.scanned_at ? new Date(data.scanned_at).toLocaleString() : null;

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <Navbar />

      <div className="max-w-7xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-3xl font-bold">Screener</h1>
            {scannedAt && (
              <p className="text-gray-400 text-sm mt-1">Last scan: {scannedAt}</p>
            )}
          </div>
          <button
            onClick={() => scanMutation.mutate()}
            disabled={isScanning}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg font-medium transition-colors"
          >
            <RefreshCw size={16} className={isScanning ? 'animate-spin' : ''} />
            {isScanning ? 'Scanning...' : 'Scan Now'}
          </button>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <p className="text-gray-400 text-sm">Volatile symbols</p>
            <p className="text-2xl font-bold mt-1">{candidates.length}</p>
          </div>
          <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <p className="text-gray-400 text-sm">UP (24h)</p>
            <p className="text-2xl font-bold mt-1 text-green-400">
              {candidates.filter(c => c.direction === 'LONG').length}
            </p>
          </div>
          <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <p className="text-gray-400 text-sm">DOWN (24h)</p>
            <p className="text-2xl font-bold mt-1 text-red-400">
              {candidates.filter(c => c.direction === 'SHORT').length}
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
                  <th className="text-right py-3 px-3">Price</th>
                  <th className="text-right py-3 px-3" title="Средний размер 1m свечи">Volat.</th>
                  <th className="text-right py-3 px-3">High 24h</th>
                  <th className="text-right py-3 px-3">Low 24h</th>
                  <th className="text-right py-3 px-3" title="Где цена в диапазоне дня: 0%=low 100%=high">Range</th>
                  <th className="text-right py-3 px-3">Vol 24h</th>
                  <th className="text-right py-3 px-3" title="% дневного объёма за последний час. Норма ~4%, аномалия >15%">Vol 1h</th>
                  <th className="text-right py-3 px-3">OI</th>
                  <th className="text-right py-3 px-3">24h %</th>
                  <th className="text-right py-3 px-3">Funding</th>
                  <th className="text-left py-3 px-3">Trend</th>
                </tr>
              </thead>
              <tbody>
                {isLoading && (
                  <tr>
                    <td colSpan={12} className="text-center py-12 text-gray-400">Loading...</td>
                  </tr>
                )}
                {!isLoading && candidates.length === 0 && (
                  <tr>
                    <td colSpan={12} className="text-center py-12 text-gray-400">
                      No data yet — press <strong>Scan Now</strong>
                    </td>
                  </tr>
                )}
                {candidates.map((c) => {
                  const ratio = volRatio(c.volume_1h, c.volume_24h);
                  return (
                    <tr key={c.symbol} className="border-t border-gray-700 hover:bg-gray-750 transition-colors">
                      <td className="py-3 px-3 font-semibold">{c.symbol.replace('USDT', '')}</td>

                      <td className="py-3 px-3 text-right text-gray-300">
                        ${formatPrice(c.last_price)}
                      </td>

                      <td className="py-3 px-3 text-right">
                        <span className={
                          c.avg_candle_size_pct >= 2 ? 'text-yellow-400 font-semibold' :
                          c.avg_candle_size_pct >= 1.5 ? 'text-orange-400 font-semibold' :
                          'text-white'
                        }>
                          {c.avg_candle_size_pct.toFixed(2)}%
                        </span>
                      </td>

                      <td className="py-3 px-3 text-right text-gray-400 text-xs">
                        ${formatPrice(c.high_24h)}
                      </td>
                      <td className="py-3 px-3 text-right text-gray-400 text-xs">
                        ${formatPrice(c.low_24h)}
                      </td>

                      <td className="py-3 px-3 text-right">
                        {c.price_range_pct !== null ? (
                          <span className={`font-semibold ${
                            c.price_range_pct >= 80 ? 'text-green-400' :
                            c.price_range_pct <= 20 ? 'text-red-400' :
                            'text-gray-300'
                          }`}>
                            {c.price_range_pct.toFixed(0)}%
                          </span>
                        ) : '—'}
                      </td>

                      <td className="py-3 px-3 text-right text-gray-300">
                        {formatVolume(c.volume_24h)}
                      </td>

                      <td className="py-3 px-3 text-right">
                        {ratio !== null ? (
                          <span className={`font-semibold ${
                            ratio >= 20 ? 'text-yellow-400' :
                            ratio >= 10 ? 'text-orange-400' :
                            'text-gray-300'
                          }`}>
                            {ratio.toFixed(1)}%
                          </span>
                        ) : '—'}
                      </td>

                      <td className="py-3 px-3 text-right text-gray-300">
                        {formatVolume(c.open_interest)}
                      </td>

                      <td className="py-3 px-3 text-right">
                        <span className={c.price_change_24h_pct >= 0 ? 'text-green-400' : 'text-red-400'}>
                          {c.price_change_24h_pct >= 0 ? '+' : ''}{c.price_change_24h_pct.toFixed(1)}%
                        </span>
                      </td>

                      <td className="py-3 px-3 text-right">
                        <span className={
                          c.funding_rate > 0.001 ? 'text-red-400' :
                          c.funding_rate < -0.001 ? 'text-green-400' :
                          'text-gray-400'
                        }>
                          {(c.funding_rate * 100).toFixed(3)}%
                        </span>
                      </td>

                      <td className="py-3 px-3">
                        <DirectionBadge direction={c.direction} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
