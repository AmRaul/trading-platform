'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { botsApi, tradingApi } from '@/lib/api';
import Navbar from '@/components/Navbar';
import { Plus, Play, Square, Trash2 } from 'lucide-react';

export default function BotsPage() {
  const queryClient = useQueryClient();
  const [showCreateModal, setShowCreateModal] = useState(false);

  const { data: bots } = useQuery({
    queryKey: ['bots'],
    queryFn: async () => (await botsApi.getAll()).data,
  });

  const { data: cryptorgBots, isLoading: cryptorgLoading, error: cryptorgError } = useQuery({
    queryKey: ['cryptorg-bots'],
    queryFn: async () => (await botsApi.getCryptorg()).data,
    refetchInterval: 30000, // Refresh every 30 seconds
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => botsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bots'] });
    },
  });

  const entryMutation = useMutation({
    mutationFn: ({ bot_id, account_balance }: any) =>
      tradingApi.manualEntry(bot_id, account_balance),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bots'] });
      queryClient.invalidateQueries({ queryKey: ['positions'] });
    },
  });

  const closeMutation = useMutation({
    mutationFn: (bot_id: number) => tradingApi.manualClose(bot_id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bots'] });
      queryClient.invalidateQueries({ queryKey: ['positions'] });
    },
  });

  const handleEntry = (bot: any) => {
    const balance = prompt('Enter account balance:');
    if (balance) {
      entryMutation.mutate({ bot_id: bot.id, account_balance: parseFloat(balance) });
    }
  };

  return (
    <div className="min-h-screen bg-gray-900">
      <Navbar />

      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-3xl font-bold">Bots</h1>
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded"
          >
            <Plus size={20} />
            Create Bot
          </button>
        </div>

        {/* Cryptorg Bots Section */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-2xl font-semibold">Cryptorg Bots</h2>
            {cryptorgLoading && <span className="text-gray-400 text-sm">Loading...</span>}
          </div>

          {cryptorgError && (
            <div className="bg-red-900 border border-red-700 text-red-200 px-4 py-3 rounded mb-4">
              Failed to load Cryptorg bots. Check API credentials and endpoint.
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {cryptorgBots?.map((bot: any, index: number) => (
              <div
                key={bot.id || index}
                className="bg-gray-800 rounded-lg border border-green-700 p-6"
              >
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h3 className="text-xl font-semibold">{bot.name || `Bot ${bot.id}`}</h3>
                    <p className="text-gray-400 text-sm">
                      {bot.symbol || bot.pairs?.[0]} - {bot.strategy?.toUpperCase()}
                    </p>
                  </div>
                  <span className="px-2 py-1 rounded text-xs bg-green-900 text-green-300">
                    CRYPTORG
                  </span>
                </div>

                <div className="space-y-2 mb-4 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-400">ID:</span>
                    <span>{bot.id}</span>
                  </div>
                  {bot.exchange && (
                    <div className="flex justify-between">
                      <span className="text-gray-400">Exchange:</span>
                      <span>{bot.exchange}</span>
                    </div>
                  )}
                  {bot.status && (
                    <div className="flex justify-between">
                      <span className="text-gray-400">Status:</span>
                      <span>{bot.status}</span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {cryptorgBots?.length === 0 && !cryptorgLoading && (
            <div className="text-center py-12 text-gray-400 border border-gray-700 rounded">
              No bots found on Cryptorg account.
            </div>
          )}
        </div>

        {/* Local Bots Section */}
        <div>
          <h2 className="text-2xl font-semibold mb-4">Local Bots</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {bots?.map((bot: any) => (
            <div
              key={bot.id}
              className="bg-gray-800 rounded-lg border border-gray-700 p-6"
            >
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h3 className="text-xl font-semibold">{bot.name}</h3>
                  <p className="text-gray-400 text-sm">
                    {bot.symbol} - {bot.side}
                  </p>
                </div>
                <span
                  className={`px-2 py-1 rounded text-xs ${
                    bot.is_active
                      ? 'bg-green-900 text-green-300'
                      : 'bg-gray-700 text-gray-300'
                  }`}
                >
                  {bot.state}
                </span>
              </div>

              <div className="space-y-2 mb-4 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-400">Leverage:</span>
                  <span>{bot.config.leverage}x</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Entry Size:</span>
                  <span>${bot.config.entry_size_usdt?.toFixed(2) || 'N/A'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Step:</span>
                  <span>{bot.config.step_percent}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Total PnL:</span>
                  <span
                    className={
                      bot.total_pnl >= 0 ? 'text-green-500' : 'text-red-500'
                    }
                  >
                    ${bot.total_pnl.toFixed(2)}
                  </span>
                </div>
              </div>

              <div className="flex gap-2">
                {bot.state === 'IDLE' ? (
                  <button
                    onClick={() => handleEntry(bot)}
                    className="flex-1 flex items-center justify-center gap-2 px-3 py-2 bg-green-600 hover:bg-green-700 rounded text-sm"
                  >
                    <Play size={16} />
                    Enter
                  </button>
                ) : (
                  <button
                    onClick={() => closeMutation.mutate(bot.id)}
                    className="flex-1 flex items-center justify-center gap-2 px-3 py-2 bg-red-600 hover:bg-red-700 rounded text-sm"
                  >
                    <Square size={16} />
                    Close
                  </button>
                )}

                <button
                  onClick={() => {
                    if (confirm('Delete this bot?')) {
                      deleteMutation.mutate(bot.id);
                    }
                  }}
                  className="px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </div>
          ))}
        </div>

          {bots?.length === 0 && (
            <div className="text-center py-12 text-gray-400 border border-gray-700 rounded">
              No local bots created yet. Click "Create Bot" to get started.
            </div>
          )}
        </div>
      </div>

      {showCreateModal && (
        <CreateBotModal onClose={() => setShowCreateModal(false)} />
      )}
    </div>
  );
}

function CreateBotModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [formData, setFormData] = useState({
    name: '',
    symbol: 'BTCUSDT',
    side: 'LONG',
    order_count: 4,
    entry_size_usdt: 10.0,
    step_percent: 4,
    leverage: 10,
    pyramiding_multiplier: 1.5,
    sl_initial: 5,
    sl_dynamic_offset: 2,
    use_trailing: true,
    trailing_percent: 1.5,
  });

  const createMutation = useMutation({
    mutationFn: (data: any) => botsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bots'] });
      onClose();
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const { name, symbol, side, ...config } = formData;
    createMutation.mutate({ name, symbol, side, config });
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-gray-800 rounded-lg max-w-2xl w-full max-h-[90vh] overflow-y-auto p-6">
        <h2 className="text-2xl font-bold mb-6">Create New Bot</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-2">Name</label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Symbol</label>
              <input
                type="text"
                value={formData.symbol}
                onChange={(e) =>
                  setFormData({ ...formData, symbol: e.target.value })
                }
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Side</label>
              <select
                value={formData.side}
                onChange={(e) => setFormData({ ...formData, side: e.target.value })}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded"
              >
                <option value="LONG">LONG</option>
                <option value="SHORT">SHORT</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Leverage</label>
              <input
                type="number"
                value={formData.leverage}
                onChange={(e) =>
                  setFormData({ ...formData, leverage: parseInt(e.target.value) })
                }
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded"
                min="1"
                max="125"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">
                Entry Size (USDT)
              </label>
              <input
                type="number"
                value={formData.entry_size_usdt}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    entry_size_usdt: parseFloat(e.target.value),
                  })
                }
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded"
                min="1"
                step="0.1"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">
                Step Percent (%)
              </label>
              <input
                type="number"
                value={formData.step_percent}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    step_percent: parseFloat(e.target.value),
                  })
                }
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded"
                step="0.1"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">
                Order Count
              </label>
              <input
                type="number"
                value={formData.order_count}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    order_count: parseInt(e.target.value),
                  })
                }
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded"
                min="1"
                max="10"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">
                Pyramiding Multiplier
              </label>
              <input
                type="number"
                value={formData.pyramiding_multiplier}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    pyramiding_multiplier: parseFloat(e.target.value),
                  })
                }
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded"
                step="0.1"
                min="1"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">
                Initial SL (%)
              </label>
              <input
                type="number"
                value={formData.sl_initial}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    sl_initial: parseFloat(e.target.value),
                  })
                }
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded"
                step="0.1"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">
                Dynamic SL Offset (%)
              </label>
              <input
                type="number"
                value={formData.sl_dynamic_offset}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    sl_dynamic_offset: parseFloat(e.target.value),
                  })
                }
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded"
                step="0.1"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">
                Trailing Percent (%)
              </label>
              <input
                type="number"
                value={formData.trailing_percent}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    trailing_percent: parseFloat(e.target.value),
                  })
                }
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded"
                step="0.1"
              />
            </div>

            <div className="flex items-center">
              <label className="flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={formData.use_trailing}
                  onChange={(e) =>
                    setFormData({ ...formData, use_trailing: e.target.checked })
                  }
                  className="mr-2"
                />
                <span className="text-sm font-medium">Use Trailing Stop</span>
              </label>
            </div>
          </div>

          <div className="flex gap-4 pt-4">
            <button
              type="submit"
              className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded"
              disabled={createMutation.isPending}
            >
              {createMutation.isPending ? 'Creating...' : 'Create Bot'}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
