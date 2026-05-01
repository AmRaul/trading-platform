'use client';

import { useQuery } from '@tanstack/react-query';
import { tradesApi } from '@/lib/api';
import Navbar from '@/components/Navbar';
import { TrendingUp, TrendingDown } from 'lucide-react';

export default function HistoryPage() {
  const { data: trades } = useQuery({
    queryKey: ['trades'],
    queryFn: async () => (await tradesApi.getAll()).data,
  });

  const winRate =
    trades?.length > 0
      ? (trades.filter((t: any) => t.pnl > 0).length / trades.length) * 100
      : 0;

  const totalPnl = trades?.reduce((sum: number, t: any) => sum + t.pnl, 0) || 0;

  return (
    <div className="min-h-screen bg-gray-900">
      <Navbar />

      <div className="max-w-7xl mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-8">Trade History</h1>

        {/* Stats */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <div className="bg-gray-800 p-6 rounded-lg border border-gray-700">
            <p className="text-gray-400 text-sm">Total Trades</p>
            <p className="text-3xl font-bold mt-2">{trades?.length || 0}</p>
          </div>

          <div className="bg-gray-800 p-6 rounded-lg border border-gray-700">
            <p className="text-gray-400 text-sm">Win Rate</p>
            <p className="text-3xl font-bold mt-2">{winRate.toFixed(1)}%</p>
          </div>

          <div className="bg-gray-800 p-6 rounded-lg border border-gray-700">
            <p className="text-gray-400 text-sm">Total PnL</p>
            <p
              className={`text-3xl font-bold mt-2 ${
                totalPnl >= 0 ? 'text-green-500' : 'text-red-500'
              }`}
            >
              ${totalPnl.toFixed(2)}
            </p>
          </div>
        </div>

        {/* Trades Table */}
        <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-700">
                <tr>
                  <th className="text-left py-4 px-4">Symbol</th>
                  <th className="text-left py-4 px-4">Side</th>
                  <th className="text-right py-4 px-4">Entry</th>
                  <th className="text-right py-4 px-4">Exit</th>
                  <th className="text-right py-4 px-4">Size</th>
                  <th className="text-right py-4 px-4">Orders</th>
                  <th className="text-right py-4 px-4">PnL</th>
                  <th className="text-left py-4 px-4">Exit Reason</th>
                  <th className="text-left py-4 px-4">Closed At</th>
                </tr>
              </thead>
              <tbody>
                {trades?.map((trade: any) => (
                  <tr key={trade.id} className="border-t border-gray-700">
                    <td className="py-4 px-4 font-medium">{trade.symbol}</td>
                    <td className="py-4 px-4">
                      <div className="flex items-center gap-2">
                        {trade.side === 'LONG' ? (
                          <TrendingUp size={16} className="text-green-500" />
                        ) : (
                          <TrendingDown size={16} className="text-red-500" />
                        )}
                        <span
                          className={
                            trade.side === 'LONG'
                              ? 'text-green-400'
                              : 'text-red-400'
                          }
                        >
                          {trade.side}
                        </span>
                      </div>
                    </td>
                    <td className="py-4 px-4 text-right">
                      ${trade.entry_price.toFixed(2)}
                    </td>
                    <td className="py-4 px-4 text-right">
                      ${trade.exit_price.toFixed(2)}
                    </td>
                    <td className="py-4 px-4 text-right">
                      {trade.total_size.toFixed(4)}
                    </td>
                    <td className="py-4 px-4 text-right">{trade.total_orders}</td>
                    <td className="py-4 px-4 text-right">
                      <div>
                        <p
                          className={`font-semibold ${
                            trade.pnl >= 0 ? 'text-green-500' : 'text-red-500'
                          }`}
                        >
                          ${trade.pnl.toFixed(2)}
                        </p>
                        <p
                          className={`text-sm ${
                            trade.pnl_percent >= 0
                              ? 'text-green-400'
                              : 'text-red-400'
                          }`}
                        >
                          {trade.pnl_percent >= 0 ? '+' : ''}
                          {trade.pnl_percent.toFixed(2)}%
                        </p>
                      </div>
                    </td>
                    <td className="py-4 px-4">
                      <span className="px-2 py-1 bg-gray-700 rounded text-xs">
                        {trade.exit_reason}
                      </span>
                    </td>
                    <td className="py-4 px-4 text-sm text-gray-400">
                      {new Date(trade.closed_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {trades?.length === 0 && (
            <div className="text-center py-12 text-gray-400">
              No trades yet
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
