'use client';

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { botsApi, tradingApi, accountsApi } from '@/lib/api';
import Navbar from '@/components/Navbar';
import { Plus, Play, Square, Trash2, Settings, Clock, X, Activity } from 'lucide-react';
import { usePriceStore, usePositionStore } from '@/lib/store';
import { wsClient } from '@/lib/websocket';
import type {
  Bot, BotEvent, CryptorgAccount, PriceUpdateEvent, PyramidingOrderEvent, TrailingStopEvent,
} from '@/lib/types';
import {
  EXCHANGE_TABS, TAB_STORAGE_KEY, COLLAPSED_STORAGE_KEY, botExchange, cardTitle, groupBots, type ExchangeTab,
} from './_components/grouping';
import GroupHeader from './_components/GroupHeader';
import PositionPanel from './_components/PositionPanel';
import StraddlePanel, { STRADDLE_REASON } from './_components/StraddlePanel';
import { signalName, trendLabel } from './_components/EntrySignalFields';
import EditBotModal from './_components/EditBotModal';
import CreateBotModal from './_components/CreateBotModal';

export default function BotsPage() {
  const queryClient = useQueryClient();
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editBot, setEditBot] = useState<Bot | null>(null);
  const [limitBot, setLimitBot] = useState<Bot | null>(null);
  const [limitPrice, setLimitPrice] = useState('');
  const { setPosition, updatePositionFields, clearPosition } = usePositionStore();
  const updatePrice = usePriceStore((s) => s.updatePrice);

  const { data: bots } = useQuery({
    queryKey: ['bots'],
    queryFn: async () => (await botsApi.getAll()).data,
    refetchInterval: 5000,
  });

  const { data: accounts = [] } = useQuery<CryptorgAccount[]>({
    queryKey: ['accounts'],
    queryFn: async () => (await accountsApi.getAll()).data,
  });

  const accountName = (id: number | null) =>
    id ? (accounts.find((a) => a.id === id)?.name ?? `#${id}`) : null;

  // Seed position store from REST response and subscribe to WS
  useEffect(() => {
    if (!bots) return;
    bots.forEach((bot) => {
      if (bot.state !== 'IDLE' && bot.open_position) {
        setPosition(bot.id, bot.open_position);
        wsClient.subscribeToPrice(bot.symbol);
      } else if (bot.state === 'STRADDLE') {
        wsClient.subscribeToPrice(bot.symbol);
      }
    });
  }, [bots]);

  // Subscribe to trading WS events
  useEffect(() => {
    const unsubPyramiding = wsClient.subscribe('pyramiding_order_added', (data: PyramidingOrderEvent) => {
      updatePositionFields(data.bot_id, {
        average_price: data.new_average_price,
        current_sl: data.new_sl,
        total_size: data.total_size,
        order_count: data.order_number,
        last_order_price: data.last_order_price ?? data.price,
        unrealized_pnl: data.unrealized_pnl,
      });
    });

    const unsubTrailing = wsClient.subscribe('trailing_stop_moved', (data: TrailingStopEvent) => {
      updatePositionFields(data.bot_id, {
        current_sl: data.new_sl,
        unrealized_pnl: data.unrealized_pnl,
      });
    });

    const handlePositionClosed = (bot_id: number) => {
      clearPosition(bot_id);
      // Optimistically set bot state to IDLE in cache so UI updates immediately
      queryClient.setQueryData<Bot[]>(['bots'], (old) => {
        if (!Array.isArray(old)) return old;
        return old.map((b) =>
          b.id === bot_id ? { ...b, state: 'IDLE', open_position: null } : b
        );
      });
      queryClient.invalidateQueries({ queryKey: ['bots'] });
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ['bots'] }), 2000);
    };

    const unsubSL = wsClient.subscribe('stop_loss_triggered', (data: BotEvent) => {
      handlePositionClosed(data.bot_id);
    });

    const unsubClosed = wsClient.subscribe('position_closed', (data: BotEvent) => {
      handlePositionClosed(data.bot_id);
    });

    const unsubPrice = wsClient.subscribe('price_update', (data: PriceUpdateEvent) => {
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

  const limitMutation = useMutation({
    mutationFn: ({ bot_id, limit_price }: { bot_id: number; limit_price: number }) =>
      tradingApi.limitEntry(bot_id, limit_price),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bots'] });
      setLimitBot(null);
      setLimitPrice('');
    },
  });

  const signalMutation = useMutation({
    mutationFn: (bot_id: number) => tradingApi.signalEntry(bot_id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bots'] }),
  });

  const cancelLimitMutation = useMutation({
    mutationFn: (bot_id: number) => tradingApi.cancelLimit(bot_id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bots'] }),
  });

  const [tab, setTab] = useState<ExchangeTab>('all');
  useEffect(() => {
    try {
      const saved = localStorage.getItem(TAB_STORAGE_KEY) as ExchangeTab | null;
      if (saved && EXCHANGE_TABS.some((t) => t.key === saved)) setTab(saved);
    } catch {}
  }, []);
  const selectTab = (key: ExchangeTab) => {
    setTab(key);
    try { localStorage.setItem(TAB_STORAGE_KEY, key); } catch {}
  };
  const inTab = (bot: Bot, key: ExchangeTab) => key === 'all' || botExchange(bot) === key;
  const shownBots = (bots ?? []).filter((b) => inTab(b, tab));
  const groups = groupBots(shownBots);

  const [collapsed, setCollapsed] = useState<string[]>([]);
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(COLLAPSED_STORAGE_KEY) ?? '[]');
      if (Array.isArray(saved)) setCollapsed(saved);
    } catch {}
  }, []);
  const toggleGroup = (key: string) => {
    setCollapsed((prev) => {
      const next = prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key];
      try { localStorage.setItem(COLLAPSED_STORAGE_KEY, JSON.stringify(next)); } catch {}
      return next;
    });
  };

  const handleEntry = (bot: Bot) => {
    entryMutation.mutate(bot.id);
  };

  const handleLimitSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!limitBot || !limitPrice) return;
    limitMutation.mutate({ bot_id: limitBot.id, limit_price: parseFloat(limitPrice) });
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

        <div className="flex gap-1 mb-3 overflow-x-auto border-b border-gray-700">
          {EXCHANGE_TABS.map(({ key, label }) => {
            const list = (bots ?? []).filter((b) => inTab(b, key));
            const open = list.filter((b) => b.state === 'PYRAMIDING' || b.state === 'STRADDLE').length;
            const active = tab === key;
            return (
              <button
                key={key}
                onClick={() => selectTab(key)}
                className={`shrink-0 flex items-center gap-1.5 px-3 py-1.5 -mb-px border-b-2 text-sm transition-colors ${
                  active ? 'border-blue-500 text-white' : 'border-transparent text-gray-400 hover:text-gray-200'
                }`}
              >
                {label}
                <span className={`px-1.5 rounded text-xs ${active ? 'bg-blue-900 text-blue-200' : 'bg-gray-800 text-gray-400'}`}>
                  {list.length}
                </span>
                {open > 0 && (
                  <span className="text-xs text-green-400" title="В позиции">● {open}</span>
                )}
              </button>
            );
          })}
        </div>

        <div className="space-y-4">
          {groups.map((g) => (
          <section key={g.key}>
          <GroupHeader group={g} collapsed={collapsed.includes(g.key)} onToggle={() => toggleGroup(g.key)} />
          {!collapsed.includes(g.key) && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {g.bots.map((bot) => (
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
                      : bot.config.bot_type === 'straddle'
                        ? 'bg-purple-900 text-purple-300'
                        : 'bg-blue-900 text-blue-300'
                  }`}>
                    {bot.config.bot_type === 'dca' ? 'DCA' : bot.config.bot_type === 'straddle' ? 'Straddle' : 'Пир'}
                  </span>
                  {bot.exchange === 'paper' && (
                    <span className="shrink-0 px-1.5 py-0.5 rounded text-xs font-medium bg-amber-900 text-amber-300">Бумажный</span>
                  )}
                  <span className="font-semibold text-sm truncate" title={bot.name}>{cardTitle(bot, g)}</span>
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
                <span className={bot.side === 'LONG' ? 'text-green-400' : bot.side === 'SHORT' ? 'text-red-400' : 'text-gray-300'}>
                  {bot.side === 'NEUTRAL' ? 'LONG+SHORT' : bot.side}
                </span>
                <span className={`text-right ${bot.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  ${bot.total_pnl.toFixed(2)}
                </span>
              </div>

              {/* Account */}
              {bot.account_id && (
                <div className="text-xs text-gray-500 mb-1">
                  <span className="text-blue-400">{accountName(bot.account_id)}</span>
                </div>
              )}

              {/* Config row */}
              <div className="flex gap-2 text-xs text-gray-500 mb-2">
                <span>{bot.config.leverage}x</span>
                <span>${bot.config.entry_size_usdt}</span>
                <span>step {bot.config.step_percent}%</span>
                <span>{bot.config.order_count} ord</span>
              </div>

              {bot.config.bot_type === 'straddle'
                ? bot.state === 'STRADDLE'
                  ? <StraddlePanel bot={bot} />
                  : bot.straddle?.done && (
                    <div className="text-xs text-gray-500 mb-1">
                      Последний запуск: <span className={bot.straddle.realized >= 0 ? 'text-green-400' : 'text-red-400'}>
                        {bot.straddle.realized >= 0 ? '+' : ''}${bot.straddle.realized.toFixed(2)}
                      </span> · {STRADDLE_REASON[bot.straddle.exit_reason] ?? bot.straddle.exit_reason}
                    </div>
                  )
                : bot.state !== 'IDLE' && <PositionPanel bot={bot} />}

              {/* Actions */}
              <div className="flex gap-1.5 mt-2">
                {bot.state === 'IDLE' ? (
                  <>
                    <button
                      onClick={() => handleEntry(bot)}
                      className="flex-1 flex items-center justify-center gap-1 px-2 py-1 bg-green-700 hover:bg-green-600 rounded text-xs"
                    >
                      <Play size={12} />
                      {bot.config.bot_type === 'straddle' ? 'Запустить сейчас' : 'Войти'}
                    </button>
                    {bot.config.entry_signal && bot.config.bot_type !== 'straddle' && (
                      <button
                        onClick={() => signalMutation.mutate(bot.id)}
                        className="flex items-center justify-center gap-1 px-2 py-1 bg-purple-800 hover:bg-purple-700 rounded text-xs"
                        title={`Ждать сигнал ${signalName(bot.config.entry_signal)} и войти автоматически`}
                      >
                        <Activity size={12} />
                        Сигнал
                      </button>
                    )}
                    {bot.config.bot_type !== 'straddle' && (
                    <button
                      onClick={() => { setLimitBot(bot); setLimitPrice(''); }}
                      className="flex items-center justify-center gap-1 px-2 py-1 bg-blue-800 hover:bg-blue-700 rounded text-xs"
                      title="Лимитный вход"
                    >
                      <Clock size={12} />
                      Лимит
                    </button>
                    )}
                  </>
                ) : bot.state === 'SIGNAL' ? (
                  <>
                    <div className="flex-1 flex items-center gap-1 px-2 py-1 bg-purple-900/50 border border-purple-700 rounded text-xs text-purple-300">
                      <Activity size={12} />
                      Жду сигнал {signalName(bot.config.entry_signal)}
                      {trendLabel(bot.config.entry_signal)}
                    </div>
                    <button
                      onClick={() => cancelLimitMutation.mutate(bot.id)}
                      className="flex items-center justify-center px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded"
                      title="Перестать ждать сигнал"
                    >
                      <X size={13} />
                    </button>
                  </>
                ) : bot.state === 'WAITING' ? (
                  <>
                    <div className="flex-1 flex items-center gap-1 px-2 py-1 bg-yellow-900/50 border border-yellow-700 rounded text-xs text-yellow-300">
                      <Clock size={12} />
                      Жду ${bot.limit_entry_price?.toFixed(4) ?? '—'}
                    </div>
                    <button
                      onClick={() => cancelLimitMutation.mutate(bot.id)}
                      className="flex items-center justify-center px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded"
                      title="Отменить лимит"
                    >
                      <X size={13} />
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => { if (confirm(`Закрыть позицию по ${bot.name}?`)) closeMutation.mutate(bot.id); }}
                    className="flex-1 flex items-center justify-center gap-1 px-2 py-1 bg-red-700 hover:bg-red-600 rounded text-xs"
                  >
                    <Square size={12} />
                    Закрыть
                  </button>
                )}
                <button
                  onClick={() => setEditBot(bot)}
                  className="px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded ml-1"
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
          </div>
          )}
          </section>
          ))}

          {bots && shownBots.length === 0 && (
            <div className="text-center py-8 text-gray-500 border border-gray-700 rounded text-sm">
              {bots.length === 0 ? 'Нет ботов. Нажмите «Создать».' : 'На этой площадке ботов нет.'}
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
      {limitBot && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-xl border border-gray-700 w-full max-w-sm p-6">
            <h2 className="text-base font-bold mb-1">Лимитный вход — {limitBot.name}</h2>
            <p className="text-xs text-gray-400 mb-4">
              {limitBot.symbol.replace('USDT', '')} {limitBot.side === 'LONG' ? '↗ LONG' : '↘ SHORT'} — вход когда цена{' '}
              {limitBot.side === 'LONG' ? 'опустится до' : 'поднимется до'}
            </p>
            <form onSubmit={handleLimitSubmit} className="space-y-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Целевая цена (USDT)</label>
                <input
                  type="number"
                  step="any"
                  required
                  autoFocus
                  value={limitPrice}
                  onChange={(e) => setLimitPrice(e.target.value)}
                  placeholder="0.00"
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                />
              </div>
              <div className="flex gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => { setLimitBot(null); setLimitPrice(''); }}
                  className="flex-1 px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm"
                >
                  Отмена
                </button>
                <button
                  type="submit"
                  disabled={limitMutation.isPending || !limitPrice}
                  className="flex-1 px-3 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg text-sm font-medium"
                >
                  {limitMutation.isPending ? 'Установка...' : 'Установить'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
