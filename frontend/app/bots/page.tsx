'use client';

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { botsApi, tradingApi } from '@/lib/api';
import Navbar from '@/components/Navbar';
import { Plus, Play, Square, Trash2, Settings } from 'lucide-react';
import { usePriceStore, usePositionStore } from '@/lib/store';
import { wsClient } from '@/lib/websocket';

export default function BotsPage() {
  const queryClient = useQueryClient();
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editBot, setEditBot] = useState<any>(null);
  const { setPosition, updatePositionFields, clearPosition } = usePositionStore();
  const updatePrice = usePriceStore((s) => s.updatePrice);

  const { data: bots } = useQuery({
    queryKey: ['bots'],
    queryFn: async () => (await botsApi.getAll()).data,
    refetchInterval: 5000,
  });

  // Seed position store from REST response and subscribe to WS
  useEffect(() => {
    if (!bots) return;
    bots.forEach((bot: any) => {
      if (bot.state !== 'IDLE' && bot.open_position) {
        setPosition(bot.id, bot.open_position);
        wsClient.subscribeToPrice(bot.symbol);
      }
    });
  }, [bots]);

  // Subscribe to trading WS events
  useEffect(() => {
    const unsubPyramiding = wsClient.subscribe('pyramiding_order_added', (data: any) => {
      updatePositionFields(data.bot_id, {
        average_price: data.new_average_price,
        current_sl: data.new_sl,
        total_size: data.total_size,
        order_count: data.order_number,
        last_order_price: data.last_order_price ?? data.price,
        unrealized_pnl: data.unrealized_pnl,
      });
    });

    const unsubTrailing = wsClient.subscribe('trailing_stop_moved', (data: any) => {
      updatePositionFields(data.bot_id, {
        current_sl: data.new_sl,
        unrealized_pnl: data.unrealized_pnl,
      });
    });

    const handlePositionClosed = (bot_id: number) => {
      clearPosition(bot_id);
      // Optimistically set bot state to IDLE in cache so UI updates immediately
      queryClient.setQueryData(['bots'], (old: any) => {
        if (!Array.isArray(old)) return old;
        return old.map((b: any) =>
          b.id === bot_id ? { ...b, state: 'IDLE', open_position: null } : b
        );
      });
      queryClient.invalidateQueries({ queryKey: ['bots'] });
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ['bots'] }), 2000);
    };

    const unsubSL = wsClient.subscribe('stop_loss_triggered', (data: any) => {
      handlePositionClosed(data.bot_id);
    });

    const unsubClosed = wsClient.subscribe('position_closed', (data: any) => {
      handlePositionClosed(data.bot_id);
    });

    const unsubPrice = wsClient.subscribe('price_update', (data: any) => {
      updatePrice(data.symbol, data.price);
    });

    const unsubReconnect = wsClient.onReconnect(() => {
      queryClient.invalidateQueries({ queryKey: ['bots'] });
    });

    return () => {
      unsubPyramiding();
      unsubTrailing();
      unsubSL();
      unsubClosed();
      unsubPrice();
      unsubReconnect();
    };
  }, []);

  const deleteMutation = useMutation({
    mutationFn: (id: number) => botsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bots'] });
    },
  });

  const entryMutation = useMutation({
    mutationFn: (bot_id: number) => tradingApi.manualEntry(bot_id, 0),
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
    entryMutation.mutate(bot.id);
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

              {bot.state !== 'IDLE' && <PositionPanel bot={bot} />}

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

                {bot.state === 'IDLE' && (
                  <button
                    onClick={() => setEditBot(bot)}
                    className="px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded"
                  >
                    <Settings size={16} />
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
      {editBot && (
        <EditBotModal bot={editBot} onClose={() => setEditBot(null)} />
      )}
    </div>
  );
}

function PositionPanel({ bot }: { bot: any }) {
  const positionData = usePositionStore((s) => s.positions[bot.id]);
  const currentPrice = usePriceStore((s) => s.prices[bot.symbol]);

  if (!positionData) return null;

  const { average_price, current_sl, order_count, unrealized_pnl, last_order_price, total_size } = positionData;
  const maxOrders = bot.config.order_count;
  const stepPercent = bot.config.step_percent;
  const tpPercent = bot.config.tp_percent;

  const nextAvgPrice = last_order_price != null
    ? bot.side === 'LONG'
      ? last_order_price * (1 + stepPercent / 100)
      : last_order_price * (1 - stepPercent / 100)
    : null;

  const tpTarget = average_price != null
    ? bot.side === 'LONG'
      ? average_price * (1 + tpPercent / 100)
      : average_price * (1 - tpPercent / 100)
    : null;

  const livePnl = currentPrice && average_price && total_size
    ? bot.side === 'LONG'
      ? (currentPrice - average_price) * total_size
      : (average_price - currentPrice) * total_size
    : unrealized_pnl;

  const fmt = (n: number | null | undefined, digits = 2) =>
    n != null ? n.toFixed(digits) : '—';

  return (
    <div className="mb-4 pt-3 border-t border-gray-600">
      {currentPrice && (
        <div className="flex justify-between text-xs mb-2">
          <span className="text-gray-400">Текущая цена</span>
          <span className="font-semibold">${fmt(currentPrice, 4)}</span>
        </div>
      )}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <div className="flex justify-between">
          <span className="text-gray-400">Средняя цена</span>
          <span className="font-semibold">${fmt(average_price, 4)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Стоп-лосс</span>
          <span className="font-semibold text-red-400">${fmt(current_sl, 4)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Усреднение в</span>
          <span className="font-semibold">${fmt(nextAvgPrice, 4)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Ордера</span>
          <span className="font-semibold">{order_count}/{maxOrders}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">PnL</span>
          <span className={`font-semibold ${livePnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
            ${fmt(livePnl, 2)}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Тейк-профит</span>
          <span className="font-semibold text-green-400">${fmt(tpTarget, 4)}</span>
        </div>
      </div>
    </div>
  );
}

function EditBotModal({ bot, onClose }: { bot: any; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [formData, setFormData] = useState({
    name: bot.name,
    symbol: bot.symbol,
    side: bot.side,
    order_count: bot.config.order_count ?? 4,
    entry_size_usdt: bot.config.entry_size_usdt ?? 10,
    step_percent: bot.config.step_percent ?? 4,
    leverage: bot.config.leverage ?? 10,
    pyramiding_multiplier: bot.config.pyramiding_multiplier ?? 1.5,
    sl_initial: bot.config.sl_initial ?? 5,
    sl_breakeven_plus: bot.config.sl_breakeven_plus ?? 0.5,
    tp_percent: bot.config.tp_percent ?? 3,
    sl_after_order3: bot.config.sl_after_order3 ?? 2,
    use_trailing: bot.config.use_trailing ?? true,
    trailing_percent: bot.config.trailing_percent ?? 1.5,
    sl_breakeven_on_order2: bot.config.sl_breakeven_on_order2 ?? true,
  });

  const updateMutation = useMutation({
    mutationFn: (data: any) => botsApi.update(bot.id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bots'] });
      onClose();
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const { name, symbol, side, ...config } = formData;
    updateMutation.mutate({ name, symbol, side, config });
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-gray-800 rounded-lg max-w-2xl w-full max-h-[90vh] overflow-y-auto p-6">
        <h2 className="text-2xl font-bold mb-6">Edit Bot — {bot.name}</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-2">Name</label>
              <input type="text" value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded" required />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Symbol</label>
              <input type="text" value={formData.symbol}
                onChange={(e) => setFormData({ ...formData, symbol: e.target.value })}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded" required />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Side</label>
              <select value={formData.side}
                onChange={(e) => setFormData({ ...formData, side: e.target.value })}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded">
                <option value="LONG">LONG</option>
                <option value="SHORT">SHORT</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Leverage</label>
              <input type="number" value={formData.leverage}
                onChange={(e) => setFormData({ ...formData, leverage: parseInt(e.target.value) })}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded" min="1" max="125" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Entry Size (USDT)</label>
              <input type="number" value={formData.entry_size_usdt}
                onChange={(e) => setFormData({ ...formData, entry_size_usdt: parseFloat(e.target.value) })}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded" min="1" step="0.1" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Step Percent (%)</label>
              <input type="number" value={formData.step_percent}
                onChange={(e) => setFormData({ ...formData, step_percent: parseFloat(e.target.value) })}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded" step="0.1" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Order Count</label>
              <input type="number" value={formData.order_count}
                onChange={(e) => setFormData({ ...formData, order_count: parseInt(e.target.value) })}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded" min="1" max="10" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Pyramiding Multiplier</label>
              <input type="number" value={formData.pyramiding_multiplier}
                onChange={(e) => setFormData({ ...formData, pyramiding_multiplier: parseFloat(e.target.value) })}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded" step="0.1" min="1" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Initial SL (%)</label>
              <input type="number" value={formData.sl_initial}
                onChange={(e) => setFormData({ ...formData, sl_initial: parseFloat(e.target.value) })}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded" step="0.1" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Take Profit (%)</label>
              <input type="number" value={formData.tp_percent}
                onChange={(e) => setFormData({ ...formData, tp_percent: parseFloat(e.target.value) })}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded" step="0.1" min="0.1" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">SL Breakeven Plus (%)</label>
              <input type="number" value={formData.sl_breakeven_plus}
                onChange={(e) => setFormData({ ...formData, sl_breakeven_plus: parseFloat(e.target.value) })}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded" step="0.1" min="0" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">SL After Order 3 (%)</label>
              <input type="number" value={formData.sl_after_order3}
                onChange={(e) => setFormData({ ...formData, sl_after_order3: parseFloat(e.target.value) })}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded" step="0.1" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Trailing Percent (%)</label>
              <input type="number" value={formData.trailing_percent}
                onChange={(e) => setFormData({ ...formData, trailing_percent: parseFloat(e.target.value) })}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded" step="0.1" />
            </div>
            <div className="flex items-center">
              <label className="flex items-center cursor-pointer">
                <input type="checkbox" checked={formData.use_trailing}
                  onChange={(e) => setFormData({ ...formData, use_trailing: e.target.checked })}
                  className="mr-2" />
                <span className="text-sm font-medium">Use Trailing Stop</span>
              </label>
            </div>
            <div className="flex items-center">
              <label className="flex items-center cursor-pointer">
                <input type="checkbox" checked={formData.sl_breakeven_on_order2}
                  onChange={(e) => setFormData({ ...formData, sl_breakeven_on_order2: e.target.checked })}
                  className="mr-2" />
                <span className="text-sm font-medium">Move SL to Breakeven on Order 2</span>
              </label>
            </div>
          </div>

          <div className="flex gap-4 pt-4">
            <button type="submit"
              className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded"
              disabled={updateMutation.isPending}>
              {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
            </button>
            <button type="button" onClick={onClose}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded">
              Cancel
            </button>
          </div>
        </form>
      </div>
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
    sl_breakeven_plus: 0.5,
    tp_percent: 3,
    sl_after_order3: 2,
    use_trailing: true,
    trailing_percent: 1.5,
    sl_breakeven_on_order2: true,
  });

  const createMutation = useMutation({
    mutationFn: (data: any) => botsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bots'] });
      onClose();
    },
  });

  const errorMessage = createMutation.error
    ? (() => {
        const detail = (createMutation.error as any)?.response?.data?.detail;
        if (Array.isArray(detail)) return detail.map((e: any) => e.msg).join(', ');
        if (typeof detail === 'string') return detail;
        return 'Failed to create bot';
      })()
    : null;

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
                Take Profit (%)
              </label>
              <input
                type="number"
                value={formData.tp_percent}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    tp_percent: parseFloat(e.target.value),
                  })
                }
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded"
                step="0.1"
                min="0.1"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">
                SL Breakeven Plus (%)
              </label>
              <input
                type="number"
                value={formData.sl_breakeven_plus}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    sl_breakeven_plus: parseFloat(e.target.value),
                  })
                }
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded"
                step="0.1"
                min="0"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">
                SL After Order 3 (%)
              </label>
              <input
                type="number"
                value={formData.sl_after_order3}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    sl_after_order3: parseFloat(e.target.value),
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
            <div className="flex items-center">
              <label className="flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={formData.sl_breakeven_on_order2}
                  onChange={(e) =>
                    setFormData({ ...formData, sl_breakeven_on_order2: e.target.checked })
                  }
                  className="mr-2"
                />
                <span className="text-sm font-medium">Move SL to Breakeven on Order 2</span>
              </label>
            </div>
          </div>

          {errorMessage && (
            <div className="text-red-400 text-sm bg-red-900/30 border border-red-700 rounded px-3 py-2">
              {errorMessage}
            </div>
          )}

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
