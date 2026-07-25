'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { signalStrategiesApi } from '@/lib/api';
import Navbar from '@/components/Navbar';
import { Plus, Trash2, Lock, Pencil } from 'lucide-react';

interface Strategy {
  id: number;
  name: string;
  is_builtin: boolean;
  is_active: boolean;
  range_min: number | null;
  range_max: number | null;
  change_min: number | null;
  change_max: number | null;
  vol_1h_min: number | null;
  side: string;
  description: string | null;
}

interface StrategyForm {
  name: string;
  range_min: string;
  range_max: string;
  change_min: string;
  change_max: string;
  vol_1h_min: string;
  side: string;
  description: string;
}

const emptyForm: StrategyForm = {
  name: '', range_min: '', range_max: '', change_min: '',
  change_max: '', vol_1h_min: '15', side: 'LONG', description: '',
};

function nullable(v: string): number | null {
  const n = parseFloat(v);
  return isNaN(n) ? null : n;
}

function rangeLabel(s: Strategy): string {
  const parts: string[] = [];
  if (s.range_min != null || s.range_max != null) {
    const lo = s.range_min != null ? `${s.range_min}%` : '—';
    const hi = s.range_max != null ? `${s.range_max}%` : '—';
    parts.push(`Range ${lo}…${hi}`);
  }
  if (s.change_min != null || s.change_max != null) {
    const lo = s.change_min != null ? `${s.change_min}%` : '—';
    const hi = s.change_max != null ? `${s.change_max}%` : '—';
    parts.push(`24h ${lo}…${hi}`);
  }
  if (s.vol_1h_min != null) parts.push(`Vol1h >${s.vol_1h_min}%`);
  return parts.join(' · ') || '—';
}

export default function SignalStrategiesPage() {
  const queryClient = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [editStrategy, setEditStrategy] = useState<Strategy | null>(null);
  const [form, setForm] = useState<StrategyForm>(emptyForm);

  const { data: strategies = [], isLoading } = useQuery<Strategy[]>({
    queryKey: ['signal-strategies'],
    queryFn: async () => (await signalStrategiesApi.getAll()).data,
  });

  const createMutation = useMutation({
    mutationFn: (f: StrategyForm) => signalStrategiesApi.create({
      name: f.name,
      range_min: nullable(f.range_min),
      range_max: nullable(f.range_max),
      change_min: nullable(f.change_min),
      change_max: nullable(f.change_max),
      vol_1h_min: nullable(f.vol_1h_min),
      side: f.side,
      description: f.description || undefined,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['signal-strategies'] });
      closeModal();
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, f }: { id: number; f: StrategyForm }) => signalStrategiesApi.update(id, {
      range_min: nullable(f.range_min),
      range_max: nullable(f.range_max),
      change_min: nullable(f.change_min),
      change_max: nullable(f.change_max),
      vol_1h_min: nullable(f.vol_1h_min),
      side: f.side,
      description: f.description || undefined,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['signal-strategies'] });
      closeModal();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => signalStrategiesApi.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['signal-strategies'] }),
  });

  const openCreate = () => {
    setEditStrategy(null);
    setForm(emptyForm);
    setShowModal(true);
  };

  const openEdit = (s: Strategy) => {
    setEditStrategy(s);
    setForm({
      name: s.name,
      range_min: s.range_min != null ? String(s.range_min) : '',
      range_max: s.range_max != null ? String(s.range_max) : '',
      change_min: s.change_min != null ? String(s.change_min) : '',
      change_max: s.change_max != null ? String(s.change_max) : '',
      vol_1h_min: s.vol_1h_min != null ? String(s.vol_1h_min) : '',
      side: s.side,
      description: s.description || '',
    });
    setShowModal(true);
  };

  const closeModal = () => {
    setShowModal(false);
    setEditStrategy(null);
    setForm(emptyForm);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editStrategy) {
      updateMutation.mutate({ id: editStrategy.id, f: form });
    } else {
      createMutation.mutate(form);
    }
  };

  const isPending = createMutation.isPending || updateMutation.isPending;
  const builtins = strategies.filter((s) => s.is_builtin);
  const custom = strategies.filter((s) => !s.is_builtin);

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <Navbar />

      <div className="max-w-4xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-3xl font-bold">Signal Strategies</h1>
            <p className="text-gray-400 text-sm mt-1">
              Встроенные нельзя удалить. Добавляй свои с нужными порогами.
            </p>
          </div>
          <button
            onClick={openCreate}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium transition-colors"
          >
            <Plus size={16} />
            Add Strategy
          </button>
        </div>

        {isLoading && <p className="text-gray-400">Loading...</p>}

        {/* Built-in */}
        {builtins.length > 0 && (
          <div className="mb-6">
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Built-in (защищены)</p>
            <div className="space-y-2">
              {builtins.map((s) => (
                <div key={s.id} className="bg-gray-800 border border-gray-700 rounded-lg p-4 flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-mono font-bold text-white">{s.name}</span>
                      <span className="px-1.5 py-0.5 bg-gray-700 text-gray-400 rounded text-xs flex items-center gap-1">
                        <Lock size={10} /> Built-in
                      </span>
                      <span className={`px-1.5 py-0.5 rounded text-xs ${s.side === 'LONG' ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'}`}>
                        {s.side}
                      </span>
                    </div>
                    {s.description && <p className="text-gray-400 text-xs mb-1">{s.description}</p>}
                    <p className="text-gray-500 text-xs font-mono">{rangeLabel(s)}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Custom */}
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">
            Пользовательские ({custom.length})
          </p>
          {custom.length === 0 && (
            <div className="text-center py-10 text-gray-600 border border-dashed border-gray-700 rounded-lg text-sm">
              Нет кастомных стратегий. Нажми «Add Strategy».
            </div>
          )}
          <div className="space-y-2">
            {custom.map((s) => (
              <div key={s.id} className="bg-gray-800 border border-gray-700 rounded-lg p-4 flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-mono font-bold text-white">{s.name}</span>
                    <span className={`px-1.5 py-0.5 rounded text-xs ${s.side === 'LONG' ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'}`}>
                      {s.side}
                    </span>
                    {!s.is_active && (
                      <span className="px-1.5 py-0.5 bg-gray-700 text-gray-500 rounded text-xs">Выкл</span>
                    )}
                  </div>
                  {s.description && <p className="text-gray-400 text-xs mb-1">{s.description}</p>}
                  <p className="text-gray-500 text-xs font-mono">{rangeLabel(s)}</p>
                </div>
                <div className="flex gap-1 shrink-0">
                  <button
                    onClick={() => openEdit(s)}
                    className="p-2 rounded hover:bg-gray-700 text-gray-400 hover:text-white transition-colors"
                    title="Edit"
                  >
                    <Pencil size={15} />
                  </button>
                  <button
                    onClick={() => { if (confirm(`Удалить стратегию ${s.name}?`)) deleteMutation.mutate(s.id); }}
                    className="p-2 rounded hover:bg-red-900 text-gray-400 hover:text-red-400 transition-colors"
                    title="Delete"
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {showModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-xl border border-gray-700 w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-bold mb-4">
              {editStrategy ? `Edit — ${editStrategy.name}` : 'New Strategy'}
            </h2>
            <form onSubmit={handleSubmit} className="space-y-3">
              {!editStrategy && (
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Name</label>
                  <input
                    type="text"
                    required
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value.toUpperCase() })}
                    placeholder="MOMENTUM_TIGHT"
                    className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white uppercase focus:outline-none focus:border-blue-500"
                  />
                </div>
              )}

              <div>
                <label className="block text-xs text-gray-400 mb-1">Side</label>
                <select
                  value={form.side}
                  onChange={(e) => setForm({ ...form, side: e.target.value })}
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="LONG">LONG</option>
                  <option value="SHORT">SHORT</option>
                </select>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Range min % (пусто = без ограничения)</label>
                  <input
                    type="number"
                    step="any"
                    value={form.range_min}
                    onChange={(e) => setForm({ ...form, range_min: e.target.value })}
                    placeholder="65"
                    className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Range max %</label>
                  <input
                    type="number"
                    step="any"
                    value={form.range_max}
                    onChange={(e) => setForm({ ...form, range_max: e.target.value })}
                    placeholder="100"
                    className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">24h change min %</label>
                  <input
                    type="number"
                    step="any"
                    value={form.change_min}
                    onChange={(e) => setForm({ ...form, change_min: e.target.value })}
                    placeholder="15"
                    className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">24h change max %</label>
                  <input
                    type="number"
                    step="any"
                    value={form.change_max}
                    onChange={(e) => setForm({ ...form, change_max: e.target.value })}
                    placeholder="100"
                    className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs text-gray-400 mb-1">Vol 1h min %</label>
                <input
                  type="number"
                  step="any"
                  value={form.vol_1h_min}
                  onChange={(e) => setForm({ ...form, vol_1h_min: e.target.value })}
                  placeholder="15"
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs text-gray-400 mb-1">Description (optional)</label>
                <input
                  type="text"
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  placeholder="Tight momentum with higher thresholds"
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div className="flex gap-2 pt-2">
                <button
                  type="button"
                  onClick={closeModal}
                  className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isPending}
                  className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg font-medium transition-colors"
                >
                  {isPending ? 'Saving...' : editStrategy ? 'Update' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
