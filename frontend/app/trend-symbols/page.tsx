'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { trendSymbolsApi } from '@/lib/api';
import Navbar from '@/components/Navbar';
import { Plus, Trash2, TrendingUp } from 'lucide-react';

interface TrendSymbol {
  id: number;
  symbol: string;
  is_active: boolean;
}

export default function TrendSymbolsPage() {
  const queryClient = useQueryClient();
  const [input, setInput] = useState('');

  const { data: symbols = [], isLoading } = useQuery<TrendSymbol[]>({
    queryKey: ['trend-symbols'],
    queryFn: async () => (await trendSymbolsApi.getAll()).data,
  });

  const addMutation = useMutation({
    mutationFn: (symbol: string) => trendSymbolsApi.add(symbol),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trend-symbols'] });
      setInput('');
    },
  });

  const removeMutation = useMutation({
    mutationFn: (id: number) => trendSymbolsApi.remove(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['trend-symbols'] }),
  });

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    const sym = input.trim().toUpperCase();
    if (!sym) return;
    addMutation.mutate(sym);
  };

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <Navbar />

      <div className="max-w-2xl mx-auto px-4 py-8">
        <div className="flex items-center gap-3 mb-6">
          <TrendingUp size={28} className="text-blue-400" />
          <h1 className="text-3xl font-bold">Trend Symbols</h1>
        </div>

        <p className="text-gray-400 text-sm mb-6">
          Symbols scanned by the trend strategy (4H/1H/15m). Changes take effect on the next scan cycle (~15 min).
        </p>

        <form onSubmit={handleAdd} className="flex gap-2 mb-8">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="SOLUSDT"
            className="flex-1 bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-white uppercase placeholder:normal-case focus:outline-none focus:border-blue-500"
          />
          <button
            type="submit"
            disabled={addMutation.isPending || !input.trim()}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg font-medium transition-colors"
          >
            <Plus size={16} />
            Add
          </button>
        </form>

        {addMutation.isError && (
          <p className="text-red-400 text-sm mb-4">
            Failed to add symbol — it may already exist.
          </p>
        )}

        {isLoading && <p className="text-gray-400">Loading...</p>}

        {!isLoading && symbols.length === 0 && (
          <div className="text-center py-16 text-gray-500">
            <TrendingUp size={48} className="mx-auto mb-4 opacity-30" />
            <p>No symbols yet</p>
          </div>
        )}

        <div className="space-y-2">
          {symbols.map((s) => (
            <div
              key={s.id}
              className="bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 flex items-center justify-between"
            >
              <span className="font-mono font-semibold text-white">{s.symbol}</span>
              <button
                onClick={() => removeMutation.mutate(s.id)}
                disabled={removeMutation.isPending}
                className="p-2 rounded hover:bg-red-900 text-gray-400 hover:text-red-400 transition-colors"
                title="Remove"
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
        </div>

        <p className="text-gray-600 text-xs mt-6">
          {symbols.length} symbol{symbols.length !== 1 ? 's' : ''} active
        </p>
      </div>
    </div>
  );
}
