'use client';

import { useQuery } from '@tanstack/react-query';
import { botsApi, positionsApi } from '@/lib/api';
import Navbar from '@/components/Navbar';
import { TrendingUp, Activity, DollarSign } from 'lucide-react';

export default function DashboardPage() {
  const { data: bots } = useQuery({
    queryKey: ['bots'],
    queryFn: async () => (await botsApi.getAll()).data,
  });

  const { data: positions } = useQuery({
    queryKey: ['positions'],
    queryFn: async () => (await positionsApi.getAll(true)).data,
  });

  const activeBots = bots?.filter((b: any) => b.is_active) || [];
  const openPositions = positions || [];
  const totalPnl = bots?.reduce((sum: number, bot: any) => sum + bot.total_pnl, 0) || 0;

  return (
    <div className="min-h-screen bg-gray-900">
      <Navbar />

      <div className="max-w-7xl mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-8">Dashboard</h1>

        {/* Stats Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <div className="bg-gray-800 p-6 rounded-lg border border-gray-700">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-gray-400 text-sm">Active Bots</p>
                <p className="text-3xl font-bold mt-2">{activeBots.length}</p>
              </div>
              <Activity className="text-blue-500" size={40} />
            </div>
          </div>

          <div className="bg-gray-800 p-6 rounded-lg border border-gray-700">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-gray-400 text-sm">Open Positions</p>
                <p className="text-3xl font-bold mt-2">{openPositions.length}</p>
              </div>
              <TrendingUp className="text-green-500" size={40} />
            </div>
          </div>

          <div className="bg-gray-800 p-6 rounded-lg border border-gray-700">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-gray-400 text-sm">Total PnL</p>
                <p
                  className={`text-3xl font-bold mt-2 ${
                    totalPnl >= 0 ? 'text-green-500' : 'text-red-500'
                  }`}
                >
                  ${totalPnl.toFixed(2)}
                </p>
              </div>
              <DollarSign className="text-yellow-500" size={40} />
            </div>
          </div>
        </div>

        {/* Active Bots */}
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-6 mb-8">
          <h2 className="text-xl font-bold mb-4">Active Bots</h2>

          {activeBots.length === 0 ? (
            <p className="text-gray-400">No active bots</p>
          ) : (
            <div className="space-y-4">
              {activeBots.map((bot: any) => (
                <div
                  key={bot.id}
                  className="bg-gray-700 p-4 rounded border border-gray-600"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="font-semibold">{bot.name}</h3>
                      <p className="text-sm text-gray-400">
                        {bot.symbol} - {bot.side}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm text-gray-400">State</p>
                      <p className="font-medium">{bot.state}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm text-gray-400">PnL</p>
                      <p
                        className={`font-medium ${
                          bot.total_pnl >= 0 ? 'text-green-500' : 'text-red-500'
                        }`}
                      >
                        ${bot.total_pnl.toFixed(2)}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Open Positions */}
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
          <h2 className="text-xl font-bold mb-4">Open Positions</h2>

          {openPositions.length === 0 ? (
            <p className="text-gray-400">No open positions</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-700">
                    <th className="text-left py-3 px-4">Symbol</th>
                    <th className="text-left py-3 px-4">Side</th>
                    <th className="text-right py-3 px-4">Size</th>
                    <th className="text-right py-3 px-4">Avg Price</th>
                    <th className="text-right py-3 px-4">Current SL</th>
                    <th className="text-right py-3 px-4">PnL</th>
                  </tr>
                </thead>
                <tbody>
                  {openPositions.map((pos: any) => (
                    <tr key={pos.id} className="border-b border-gray-700">
                      <td className="py-3 px-4">{pos.symbol}</td>
                      <td className="py-3 px-4">
                        <span
                          className={`px-2 py-1 rounded text-sm ${
                            pos.side === 'LONG'
                              ? 'bg-green-900 text-green-300'
                              : 'bg-red-900 text-red-300'
                          }`}
                        >
                          {pos.side}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right">{pos.total_size.toFixed(4)}</td>
                      <td className="py-3 px-4 text-right">
                        ${pos.average_price?.toFixed(2)}
                      </td>
                      <td className="py-3 px-4 text-right">
                        ${pos.current_sl?.toFixed(2)}
                      </td>
                      <td
                        className={`py-3 px-4 text-right font-medium ${
                          pos.unrealized_pnl >= 0 ? 'text-green-500' : 'text-red-500'
                        }`}
                      >
                        ${pos.unrealized_pnl.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
