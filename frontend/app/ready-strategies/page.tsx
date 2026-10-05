'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { readyStrategiesApi } from '@/lib/api';
import Navbar from '@/components/Navbar';
import { TrendingUp, TrendingDown, ChevronRight } from 'lucide-react';

function Metric({ label, value, tone }: { label: string; value: string; tone?: 'up' | 'down' }) {
  return (
    <div>
      <p className="text-gray-400 text-xs">{label}</p>
      <p
        className={`text-lg font-semibold mt-1 ${
          tone === 'up' ? 'text-green-500' : tone === 'down' ? 'text-red-500' : ''
        }`}
      >
        {value}
      </p>
    </div>
  );
}

export default function ReadyStrategiesPage() {
  const { data: strategies, isLoading } = useQuery({
    queryKey: ['ready-strategies'],
    queryFn: async () => (await readyStrategiesApi.getAll()).data,
  });

  return (
    <div className="min-h-screen bg-gray-900">
      <Navbar />

      <div className="max-w-7xl mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-2">Готовые стратегии</h1>
        <p className="text-gray-400 mb-8">
          Проверенные стратегии с бэктестом на истории. Изучите правила и результаты, затем запустите на своём аккаунте.
        </p>

        {isLoading && <p className="text-gray-400">Загрузка…</p>}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {strategies?.map((s: any) => (
            <Link
              key={s.slug}
              href={`/ready-strategies/${s.slug}`}
              className="block bg-gray-800 p-6 rounded-lg border border-gray-700 hover:border-gray-500 transition-colors"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    {s.side === 'LONG' ? (
                      <TrendingUp size={18} className="text-green-500 shrink-0" />
                    ) : (
                      <TrendingDown size={18} className="text-red-500 shrink-0" />
                    )}
                    <h2 className="text-xl font-semibold">{s.name}</h2>
                  </div>
                  <p className="text-xs text-gray-500">
                    {s.symbol} · {s.side} · {s.timeframe}
                  </p>
                </div>
                <span
                  className={`text-xs px-2 py-1 rounded shrink-0 ${
                    s.launch_available ? 'bg-green-900 text-green-300' : 'bg-gray-700 text-gray-300'
                  }`}
                >
                  {s.launch_available ? 'Можно запустить' : 'Скоро запуск'}
                </span>
              </div>

              <p className="text-gray-300 text-sm mt-4">{s.summary}</p>

              <div className="mt-6 pt-4 border-t border-gray-700 space-y-4">
                {s.variants.map((v: any) => (
                  <div key={v.key}>
                    <p className="text-xs uppercase tracking-wide text-gray-500 mb-2">{v.name}</p>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                      <Metric
                        label="В год (≈)"
                        value={`${v.metrics.avg_annual_return_pct >= 0 ? '+' : ''}${v.metrics.avg_annual_return_pct}%`}
                        tone={v.metrics.avg_annual_return_pct >= 0 ? 'up' : 'down'}
                      />
                      <Metric
                        label="За период"
                        value={`${v.metrics.total_return_pct >= 0 ? '+' : ''}${v.metrics.total_return_pct}%`}
                      />
                      <Metric label="Макс. просадка" value={`${v.metrics.max_drawdown_pct}%`} tone="down" />
                      <Metric label="Сделок" value={String(v.metrics.trades)} />
                    </div>
                  </div>
                ))}
              </div>

              <div className="flex items-center gap-1 text-sm text-blue-400 mt-4">
                Подробнее и бэктест <ChevronRight size={16} />
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
