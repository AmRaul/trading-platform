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

      <div className="max-w-7xl mx-auto px-3 py-4">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-xl font-bold">Боты</h1>
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-sm"
          >
            <Plus size={16} />
            Создать
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {bots?.map((bot: any) => (
            <div
              key={bot.id}
              className="bg-gray-800 rounded border border-gray-700 p-3"
            >
              {/* Header */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-1.5 min-w-0">
                  <span className={`shrink-0 px-1.5 py-0.5 rounded text-xs font-medium ${
                    bot.config.bot_type === 'dca'
                      ? 'bg-orange-900 text-orange-300'
                      : 'bg-blue-900 text-blue-300'
                  }`}>
                    {bot.config.bot_type === 'dca' ? 'DCA' : 'Пир'}
                  </span>
                  <span className="font-semibold text-sm truncate">{bot.name}</span>
                </div>
                <span className={`shrink-0 px-1.5 py-0.5 rounded text-xs ${
                  bot.state !== 'IDLE' ? 'bg-green-900 text-green-300' : 'bg-gray-700 text-gray-400'
                }`}>
                  {bot.state}
                </span>
              </div>

              {/* Symbol / Side / Stats */}
              <div className="grid grid-cols-3 gap-x-2 text-xs text-gray-400 mb-2">
                <span>{bot.symbol.replace('USDT', '')}</span>
                <span className={bot.side === 'LONG' ? 'text-green-400' : 'text-red-400'}>{bot.side}</span>
                <span className={`text-right ${bot.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  ${bot.total_pnl.toFixed(2)}
                </span>
              </div>

              {/* Config row */}
              <div className="flex gap-2 text-xs text-gray-500 mb-2">
                <span>{bot.config.leverage}x</span>
                <span>${bot.config.entry_size_usdt}</span>
                <span>step {bot.config.step_percent}%</span>
                <span>{bot.config.order_count} ord</span>
              </div>

              {bot.state !== 'IDLE' && <PositionPanel bot={bot} />}

              {/* Actions */}
              <div className="flex gap-1.5 mt-2">
                {bot.state === 'IDLE' ? (
                  <button
                    onClick={() => handleEntry(bot)}
                    className="flex-1 flex items-center justify-center gap-1 px-2 py-1 bg-green-700 hover:bg-green-600 rounded text-xs"
                  >
                    <Play size={12} />
                    Войти
                  </button>
                ) : (
                  <button
                    onClick={() => closeMutation.mutate(bot.id)}
                    className="flex-1 flex items-center justify-center gap-1 px-2 py-1 bg-red-700 hover:bg-red-600 rounded text-xs"
                  >
                    <Square size={12} />
                    Закрыть
                  </button>
                )}
                <button
                  onClick={() => setEditBot(bot)}
                  className="px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded"
                  title={bot.state !== 'IDLE' ? 'Изменения применятся со следующей сделки' : 'Настройки'}
                >
                  <Settings size={13} />
                </button>
                <button
                  onClick={() => { if (confirm('Удалить бота?')) deleteMutation.mutate(bot.id); }}
                  className="px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          ))}

          {bots?.length === 0 && (
            <div className="col-span-full text-center py-8 text-gray-500 border border-gray-700 rounded text-sm">
              Нет ботов. Нажмите «Создать».
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

  const botType = bot.config.bot_type ?? 'pyramiding';
  const nextAvgPrice = last_order_price != null && average_price != null
    ? botType === 'dca'
      ? bot.side === 'LONG'
        ? average_price * (1 - stepPercent / 100)
        : average_price * (1 + stepPercent / 100)
      : bot.side === 'LONG'
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
    <div className="pt-2 border-t border-gray-700 mb-1">
      {currentPrice && (
        <div className="flex justify-between text-xs mb-1">
          <span className="text-gray-500">Цена</span>
          <span className="font-medium">${fmt(currentPrice, 4)}</span>
        </div>
      )}
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
        <div className="flex justify-between">
          <span className="text-gray-500">Avg</span>
          <span>${fmt(average_price, 4)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">SL</span>
          <span className="text-red-400">${fmt(current_sl, 4)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">{botType === 'dca' ? 'DCA↓' : 'Пир↑'}</span>
          <span>${fmt(nextAvgPrice, 4)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Орд</span>
          <span>{order_count}/{maxOrders}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">PnL</span>
          <span className={livePnl >= 0 ? 'text-green-400' : 'text-red-400'}>${fmt(livePnl, 2)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">TP</span>
          <span className="text-green-400">${fmt(tpTarget, 4)}</span>
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
    bot_type: bot.config.bot_type ?? 'pyramiding',
    order_count: bot.config.order_count ?? 4,
    entry_size_usdt: bot.config.entry_size_usdt ?? 10,
    step_percent: bot.config.step_percent ?? 4,
    leverage: bot.config.leverage ?? 10,
    pyramiding_multiplier: bot.config.pyramiding_multiplier ?? 1.5,
    dca_multiplier: bot.config.dca_multiplier ?? 1.0,
    dca_active_orders: bot.config.dca_active_orders ?? 3,
    dca_multiplier_price: bot.config.dca_multiplier_price ?? 1.0,
    sl_enabled: bot.config.sl_initial !== null && bot.config.sl_initial !== undefined,
    sl_initial: bot.config.sl_initial ?? 5,
    sl_breakeven_plus: bot.config.sl_breakeven_plus ?? 0.5,
    tp_percent: bot.config.tp_percent ?? 3,
    sl_after_order3: bot.config.sl_after_order3 ?? 2,
    use_trailing: bot.config.use_trailing ?? true,
    trailing_percent: bot.config.trailing_percent ?? 1.5,
    sl_breakeven_on_order2: bot.config.sl_breakeven_on_order2 ?? true,
    cycle: bot.config.cycle ?? false,
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
    const { name, symbol, side, sl_enabled, ...rest } = formData;
    const config = { ...rest, sl_initial: sl_enabled ? rest.sl_initial : null };
    updateMutation.mutate({ name, symbol, side, config });
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center p-3 z-50">
      <div className="bg-gray-800 rounded-lg max-w-xl w-full max-h-[90vh] overflow-y-auto p-4">
        <h2 className="text-base font-bold mb-2">Редактировать — {bot.name}</h2>

        {bot.state !== 'IDLE' && (
          <div className="mb-3 px-2 py-1.5 bg-yellow-900/40 border border-yellow-700 rounded text-yellow-300 text-xs">
            Бот активен — изменения применятся со следующей сделки
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3">
          {/* Bot type toggle */}
          <div className="flex rounded overflow-hidden border border-gray-600">
            <button type="button"
              onClick={() => setFormData({ ...formData, bot_type: 'pyramiding' })}
              className={`flex-1 py-1.5 text-xs font-medium transition-colors ${formData.bot_type === 'pyramiding' ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'}`}>
              Пирамидинг
            </button>
            <button type="button"
              onClick={() => setFormData({ ...formData, bot_type: 'dca' })}
              className={`flex-1 py-1.5 text-xs font-medium transition-colors ${formData.bot_type === 'dca' ? 'bg-orange-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'}`}>
              DCA
            </button>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Название</label>
              <input type="text" value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" required />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Символ</label>
              <input type="text" value={formData.symbol}
                onChange={(e) => setFormData({ ...formData, symbol: e.target.value.toUpperCase() })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" required />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Сторона</label>
              <select value={formData.side}
                onChange={(e) => setFormData({ ...formData, side: e.target.value })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded">
                <option value="LONG">LONG</option>
                <option value="SHORT">SHORT</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Плечо</label>
              <input type="number" value={formData.leverage}
                onChange={(e) => setFormData({ ...formData, leverage: parseInt(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" min="1" max="125" />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Размер входа (USDT)</label>
              <input type="number" value={formData.entry_size_usdt}
                onChange={(e) => setFormData({ ...formData, entry_size_usdt: parseFloat(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" min="1" step="0.1" />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">
                Шаг % {formData.bot_type === 'dca' ? '(усреднение ↓)' : '(триггер ↑)'}
              </label>
              <input type="number" value={formData.step_percent}
                onChange={(e) => setFormData({ ...formData, step_percent: parseFloat(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" step="0.1" />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Кол-во ордеров</label>
              <input type="number" value={formData.order_count}
                onChange={(e) => setFormData({ ...formData, order_count: parseInt(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" min="1" max="10" />
            </div>

            {formData.bot_type === 'pyramiding' ? (
              <div>
                <label className="block text-xs text-gray-400 mb-1">Мультипликатор пир.</label>
                <input type="number" value={formData.pyramiding_multiplier}
                  onChange={(e) => setFormData({ ...formData, pyramiding_multiplier: parseFloat(e.target.value) })}
                  className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" step="0.1" min="1" />
              </div>
            ) : (
              <>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">DCA мульт. объёма</label>
                  <input type="number" value={formData.dca_multiplier}
                    onChange={(e) => setFormData({ ...formData, dca_multiplier: parseFloat(e.target.value) })}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" step="0.1" min="1" />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Активных DCA ордеров</label>
                  <input type="number" value={formData.dca_active_orders}
                    onChange={(e) => setFormData({ ...formData, dca_active_orders: parseInt(e.target.value) })}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" min="1" max="10" />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">DCA мульт. шага цены</label>
                  <input type="number" value={formData.dca_multiplier_price}
                    onChange={(e) => setFormData({ ...formData, dca_multiplier_price: parseFloat(e.target.value) })}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" step="0.1" min="1" />
                </div>
              </>
            )}

            <div>
              <label className="block text-xs text-gray-400 mb-1">
                <span className="flex items-center gap-1.5">
                  <input type="checkbox" checked={formData.sl_enabled}
                    onChange={(e) => setFormData({ ...formData, sl_enabled: e.target.checked })} />
                  Стоп-лосс (%)
                </span>
              </label>
              <input type="number" value={formData.sl_initial}
                onChange={(e) => setFormData({ ...formData, sl_initial: parseFloat(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded disabled:opacity-40"
                step="0.1" disabled={!formData.sl_enabled} />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">Тейк-профит (%)</label>
              <input type="number" value={formData.tp_percent}
                onChange={(e) => setFormData({ ...formData, tp_percent: parseFloat(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" step="0.1" min="0.1" />
            </div>

            {formData.bot_type === 'pyramiding' && (
              <>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">SL безубыток + (%)</label>
                  <input type="number" value={formData.sl_breakeven_plus}
                    onChange={(e) => setFormData({ ...formData, sl_breakeven_plus: parseFloat(e.target.value) })}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" step="0.1" min="0" />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">SL после ордера 3 (%)</label>
                  <input type="number" value={formData.sl_after_order3}
                    onChange={(e) => setFormData({ ...formData, sl_after_order3: parseFloat(e.target.value) })}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" step="0.1" />
                </div>
              </>
            )}

            <div>
              <label className="block text-xs text-gray-400 mb-1">Трейлинг (%)</label>
              <input type="number" value={formData.trailing_percent}
                onChange={(e) => setFormData({ ...formData, trailing_percent: parseFloat(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" step="0.1" />
            </div>

            <div className="flex items-center">
              <label className="flex items-center gap-1.5 cursor-pointer text-xs">
                <input type="checkbox" checked={formData.use_trailing}
                  onChange={(e) => setFormData({ ...formData, use_trailing: e.target.checked })} />
                Трейлинг стоп
              </label>
            </div>

            <div className="flex items-center">
              <label className="flex items-center gap-1.5 cursor-pointer text-xs">
                <input type="checkbox" checked={formData.cycle}
                  onChange={(e) => setFormData({ ...formData, cycle: e.target.checked })} />
                Цикл (авто-перезапуск)
              </label>
            </div>

            {formData.bot_type === 'pyramiding' && (
              <div className="flex items-center">
                <label className="flex items-center gap-1.5 cursor-pointer text-xs">
                  <input type="checkbox" checked={formData.sl_breakeven_on_order2}
                    onChange={(e) => setFormData({ ...formData, sl_breakeven_on_order2: e.target.checked })} />
                  SL в безубыток на ордере 2
                </label>
              </div>
            )}
          </div>

          <div className="flex gap-2 pt-2">
            <button type="submit"
              className="flex-1 px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 rounded"
              disabled={updateMutation.isPending}>
              {updateMutation.isPending ? 'Сохранение...' : 'Сохранить'}
            </button>
            <button type="button" onClick={onClose}
              className="px-3 py-1.5 text-sm bg-gray-700 hover:bg-gray-600 rounded">
              Отмена
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
    bot_type: 'pyramiding',
    order_count: 4,
    entry_size_usdt: 10.0,
    step_percent: 4,
    leverage: 10,
    pyramiding_multiplier: 1.5,
    dca_multiplier: 1.0,
    dca_active_orders: 3,
    dca_multiplier_price: 1.0,
    sl_enabled: true,
    sl_initial: 5,
    sl_breakeven_plus: 0.5,
    tp_percent: 3,
    sl_after_order3: 2,
    use_trailing: true,
    trailing_percent: 1.5,
    sl_breakeven_on_order2: true,
    cycle: false,
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
    const { name, symbol, side, sl_enabled, ...rest } = formData;
    const config = { ...rest, sl_initial: sl_enabled ? rest.sl_initial : null };
    createMutation.mutate({ name, symbol, side, config });
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center p-3 z-50">
      <div className="bg-gray-800 rounded-lg max-w-xl w-full max-h-[90vh] overflow-y-auto p-4">
        <h2 className="text-base font-bold mb-3">Создать бота</h2>

        <form onSubmit={handleSubmit} className="space-y-3">
          {/* Bot type toggle */}
          <div className="flex rounded overflow-hidden border border-gray-600">
            <button
              type="button"
              onClick={() => setFormData({ ...formData, bot_type: 'pyramiding' })}
              className={`flex-1 py-1.5 text-xs font-medium transition-colors ${
                formData.bot_type === 'pyramiding' ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
              }`}
            >
              Пирамидинг
            </button>
            <button
              type="button"
              onClick={() => setFormData({ ...formData, bot_type: 'dca' })}
              className={`flex-1 py-1.5 text-xs font-medium transition-colors ${
                formData.bot_type === 'dca' ? 'bg-orange-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
              }`}
            >
              DCA
            </button>
          </div>

          <p className="text-xs text-gray-500">
            {formData.bot_type === 'pyramiding'
              ? 'Добавляет ордера когда цена идёт в нашу сторону.'
              : 'Cryptorg ставит лимитки ниже рынка, усредняет позицию.'}
          </p>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Название</label>
              <input type="text" value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" required />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">Символ</label>
              <input type="text" value={formData.symbol}
                onChange={(e) => setFormData({ ...formData, symbol: e.target.value })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" required />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">Сторона</label>
              <select value={formData.side}
                onChange={(e) => setFormData({ ...formData, side: e.target.value })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded">
                <option value="LONG">LONG</option>
                <option value="SHORT">SHORT</option>
              </select>
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">Плечо</label>
              <input type="number" value={formData.leverage}
                onChange={(e) => setFormData({ ...formData, leverage: parseInt(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                min="1" max="125" />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">Размер входа (USDT)</label>
              <input type="number" value={formData.entry_size_usdt}
                onChange={(e) => setFormData({ ...formData, entry_size_usdt: parseFloat(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                min="1" step="0.1" />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">
                Шаг % {formData.bot_type === 'dca' ? '(усреднение ↓)' : '(триггер ↑)'}
              </label>
              <input type="number" value={formData.step_percent}
                onChange={(e) => setFormData({ ...formData, step_percent: parseFloat(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" step="0.1" />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">Кол-во ордеров</label>
              <input type="number" value={formData.order_count}
                onChange={(e) => setFormData({ ...formData, order_count: parseInt(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                min="1" max="10" />
            </div>

            {formData.bot_type === 'pyramiding' ? (
              <div>
                <label className="block text-xs text-gray-400 mb-1">Мультипликатор пир.</label>
                <input type="number" value={formData.pyramiding_multiplier}
                  onChange={(e) => setFormData({ ...formData, pyramiding_multiplier: parseFloat(e.target.value) })}
                  className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                  step="0.1" min="1" />
              </div>
            ) : (
              <>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">DCA мульт. объёма</label>
                  <input type="number" value={formData.dca_multiplier}
                    onChange={(e) => setFormData({ ...formData, dca_multiplier: parseFloat(e.target.value) })}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                    step="0.1" min="1" />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Активных DCA ордеров</label>
                  <input type="number" value={formData.dca_active_orders}
                    onChange={(e) => setFormData({ ...formData, dca_active_orders: parseInt(e.target.value) })}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                    min="1" max="10" />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">DCA мульт. шага цены</label>
                  <input type="number" value={formData.dca_multiplier_price}
                    onChange={(e) => setFormData({ ...formData, dca_multiplier_price: parseFloat(e.target.value) })}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                    step="0.1" min="1" />
                </div>
              </>
            )}

            <div>
              <label className="block text-xs text-gray-400 mb-1">
                <span className="flex items-center gap-1.5">
                  <input type="checkbox" checked={formData.sl_enabled}
                    onChange={(e) => setFormData({ ...formData, sl_enabled: e.target.checked })} />
                  Стоп-лосс (%)
                </span>
              </label>
              <input type="number" value={formData.sl_initial}
                onChange={(e) => setFormData({ ...formData, sl_initial: parseFloat(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded disabled:opacity-40"
                step="0.1" disabled={!formData.sl_enabled} />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">Тейк-профит (%)</label>
              <input type="number" value={formData.tp_percent}
                onChange={(e) => setFormData({ ...formData, tp_percent: parseFloat(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                step="0.1" min="0.1" />
            </div>

            {formData.bot_type === 'pyramiding' && (
              <>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">SL безубыток + (%)</label>
                  <input type="number" value={formData.sl_breakeven_plus}
                    onChange={(e) => setFormData({ ...formData, sl_breakeven_plus: parseFloat(e.target.value) })}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                    step="0.1" min="0" />
                </div>

                <div>
                  <label className="block text-xs text-gray-400 mb-1">SL после ордера 3 (%)</label>
                  <input type="number" value={formData.sl_after_order3}
                    onChange={(e) => setFormData({ ...formData, sl_after_order3: parseFloat(e.target.value) })}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" step="0.1" />
                </div>
              </>
            )}

            <div>
              <label className="block text-xs text-gray-400 mb-1">Трейлинг (%)</label>
              <input type="number" value={formData.trailing_percent}
                onChange={(e) => setFormData({ ...formData, trailing_percent: parseFloat(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" step="0.1" />
            </div>

            <div className="flex items-center">
              <label className="flex items-center gap-1.5 cursor-pointer text-xs">
                <input type="checkbox" checked={formData.use_trailing}
                  onChange={(e) => setFormData({ ...formData, use_trailing: e.target.checked })} />
                Трейлинг стоп
              </label>
            </div>

            <div className="flex items-center">
              <label className="flex items-center gap-1.5 cursor-pointer text-xs">
                <input type="checkbox" checked={formData.cycle}
                  onChange={(e) => setFormData({ ...formData, cycle: e.target.checked })} />
                Цикл (авто-перезапуск)
              </label>
            </div>

            {formData.bot_type === 'pyramiding' && (
              <div className="flex items-center">
                <label className="flex items-center gap-1.5 cursor-pointer text-xs">
                  <input type="checkbox" checked={formData.sl_breakeven_on_order2}
                    onChange={(e) => setFormData({ ...formData, sl_breakeven_on_order2: e.target.checked })} />
                  SL в безубыток на ордере 2
                </label>
              </div>
            )}
          </div>

          {errorMessage && (
            <div className="text-red-400 text-xs bg-red-900/30 border border-red-700 rounded px-2 py-1.5">
              {errorMessage}
            </div>
          )}

          <div className="flex gap-2 pt-2">
            <button type="submit"
              className="flex-1 px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 rounded"
              disabled={createMutation.isPending}>
              {createMutation.isPending ? 'Создание...' : 'Создать'}
            </button>
            <button type="button" onClick={onClose}
              className="px-3 py-1.5 text-sm bg-gray-700 hover:bg-gray-600 rounded">
              Отмена
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
