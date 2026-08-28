'use client';

import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { positionsApi } from '@/lib/api';
import Navbar from '@/components/Navbar';
import { wsClient } from '@/lib/websocket';
import { usePriceStore } from '@/lib/store';

export default function PositionsPage() {
  const prices = usePriceStore((state) => state.prices);
  const updatePrice = usePriceStore((state) => state.updatePrice);
  const queryClient = useQueryClient();

  const { data: positions, refetch } = useQuery({
    queryKey: ['positions', true],
    queryFn: async () => (await positionsApi.getAll(true)).data,
    refetchInterval: 5000,
  });

  const setManagedMutation = useMutation({
    mutationFn: ({ id, is_bot_managed }: { id: number; is_bot_managed: boolean }) =>
      positionsApi.setManaged(id, is_bot_managed),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['positions'] });
    },
  });

  const handleToggleManaged = (pos: any) => {
    if (pos.is_bot_managed) {
      const confirmed = window.confirm(
        `Отключить бота на позиции ${pos.symbol}? Бот перестанет проверять Stop Loss, докупать и обновлять trailing — дальше вести сделку придётся вручную.`
      );
      if (!confirmed) return;
    }
    setManagedMutation.mutate({ id: pos.id, is_bot_managed: !pos.is_bot_managed });
  };

  const setTrailingMutation = useMutation({
    mutationFn: ({ id, trailing_enabled }: { id: number; trailing_enabled: boolean }) =>
      positionsApi.setTrailingFrozen(id, trailing_enabled),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['positions'] });
    },
    onError: (error: any) => {
      const detail = error?.response?.data?.detail || 'Не удалось изменить trailing SL';
      window.alert(`Ошибка: ${detail}\n\nБиржа могла не подтвердить изменение — состояние на бирже не поменялось.`);
    },
  });

  const handleToggleTrailing = (pos: any) => {
    setTrailingMutation.mutate({ id: pos.id, trailing_enabled: !pos.trailing_enabled });
  };

  useEffect(() => {
    // Subscribe to price updates
    const unsubscribe = wsClient.subscribe('price_update', (data) => {
      updatePrice(data.symbol, data.price);
    });

    // Subscribe to all active position symbols
    positions?.forEach((pos: any) => {
      wsClient.subscribeToPrice(pos.symbol);
    });

    return () => {
      unsubscribe();
    };
  }, [positions, updatePrice]);

  return (
    <div className="min-h-screen bg-gray-900">
      <Navbar />

      <div className="max-w-7xl mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-8">Open Positions</h1>

        {positions?.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            No open positions
          </div>
        ) : (
          <div className="space-y-6">
            {positions?.map((pos: any) => {
              const currentPrice = prices[pos.symbol];
              const unrealizedPnl = currentPrice
                ? pos.side === 'LONG'
                  ? (currentPrice - pos.average_price) * pos.total_size
                  : (pos.average_price - currentPrice) * pos.total_size
                : pos.unrealized_pnl;

              const pnlPercent = currentPrice && pos.average_price
                ? pos.side === 'LONG'
                  ? ((currentPrice - pos.average_price) / pos.average_price) * 100
                  : ((pos.average_price - currentPrice) / pos.average_price) * 100
                : 0;

              return (
                <div
                  key={pos.id}
                  className={`bg-gray-800 rounded-lg border p-6 ${
                    pos.is_bot_managed ? 'border-gray-700' : 'border-amber-600'
                  }`}
                >
                  <div className="flex items-start justify-between mb-6">
                    <div>
                      <h3 className="text-2xl font-bold">{pos.symbol}</h3>
                      <div className="flex items-center gap-2 mt-2">
                        <span
                          className={`inline-block px-3 py-1 rounded text-sm font-medium ${
                            pos.side === 'LONG'
                              ? 'bg-green-900 text-green-300'
                              : 'bg-red-900 text-red-300'
                          }`}
                        >
                          {pos.side}
                        </span>
                        <span
                          className={`inline-block px-3 py-1 rounded text-sm font-medium ${
                            pos.is_bot_managed
                              ? 'bg-blue-900 text-blue-300'
                              : 'bg-amber-900 text-amber-300'
                          }`}
                        >
                          {pos.is_bot_managed ? 'Bot managed' : 'Manual control'}
                        </span>
                        {!pos.trailing_enabled && (
                          <span className="inline-block px-3 py-1 rounded text-sm font-medium bg-cyan-900 text-cyan-300">
                            Trailing off
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="text-right">
                      <p className="text-gray-400 text-sm">Unrealized PnL</p>
                      <p
                        className={`text-3xl font-bold ${
                          unrealizedPnl >= 0 ? 'text-green-500' : 'text-red-500'
                        }`}
                      >
                        ${unrealizedPnl.toFixed(2)}
                      </p>
                      <p
                        className={`text-sm ${
                          pnlPercent >= 0 ? 'text-green-400' : 'text-red-400'
                        }`}
                      >
                        {pnlPercent >= 0 ? '+' : ''}
                        {pnlPercent.toFixed(2)}%
                      </p>
                      <div className="flex flex-col gap-2 mt-3">
                        <button
                          onClick={() => handleToggleManaged(pos)}
                          disabled={setManagedMutation.isPending}
                          className={`px-3 py-1.5 rounded text-sm font-medium transition-colors disabled:opacity-50 ${
                            pos.is_bot_managed
                              ? 'bg-amber-700 hover:bg-amber-600 text-white'
                              : 'bg-blue-700 hover:bg-blue-600 text-white'
                          }`}
                        >
                          {pos.is_bot_managed ? 'Взять под ручное управление' : 'Вернуть боту'}
                        </button>
                        {pos.is_bot_managed && (
                          <button
                            onClick={() => handleToggleTrailing(pos)}
                            disabled={setTrailingMutation.isPending}
                            className={`px-3 py-1.5 rounded text-sm font-medium transition-colors disabled:opacity-50 ${
                              !pos.trailing_enabled
                                ? 'bg-cyan-700 hover:bg-cyan-600 text-white'
                                : 'bg-gray-700 hover:bg-gray-600 text-white'
                            }`}
                          >
                            {pos.trailing_enabled ? 'Отключить trailing SL' : 'Включить trailing SL'}
                          </button>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div>
                      <p className="text-gray-400 text-sm">Current Price</p>
                      <p className="text-lg font-semibold">
                        ${currentPrice?.toFixed(2) || 'Loading...'}
                      </p>
                    </div>

                    <div>
                      <p className="text-gray-400 text-sm">Average Price</p>
                      <p className="text-lg font-semibold">
                        ${pos.average_price?.toFixed(2)}
                      </p>
                    </div>

                    <div>
                      <p className="text-gray-400 text-sm">Total Size</p>
                      <p className="text-lg font-semibold">
                        {pos.total_size.toFixed(4)}
                      </p>
                    </div>

                    <div>
                      <p className="text-gray-400 text-sm">Orders</p>
                      <p className="text-lg font-semibold">{pos.order_count}</p>
                    </div>

                    <div>
                      <p className="text-gray-400 text-sm">Stop Loss</p>
                      <p className="text-lg font-semibold text-red-400">
                        ${pos.current_sl?.toFixed(2)}
                      </p>
                    </div>

                    <div>
                      <p className="text-gray-400 text-sm">Trailing SL</p>
                      <p className="text-lg font-semibold">
                        {pos.trailing_sl
                          ? `$${pos.trailing_sl.toFixed(2)}`
                          : 'N/A'}
                      </p>
                    </div>

                    <div>
                      <p className="text-gray-400 text-sm">Opened</p>
                      <p className="text-sm">
                        {new Date(pos.opened_at).toLocaleString()}
                      </p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
