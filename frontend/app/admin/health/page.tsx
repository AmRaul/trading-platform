'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { adminApi } from '@/lib/api';
import Navbar from '@/components/Navbar';

interface DesyncedBot {
  bot_id: number;
  symbol: string;
  state: string;
  owner_username: string;
}

interface AdminHealth {
  redis_ok: boolean;
  redis_error: string | null;
  price_tracker_ok: boolean;
  price_tracker_error: string | null;
  price_tracker_subscriptions: Record<string, string[]>;
  registered_bots_count: number;
  db_active_bots_count: number;
  desynced_bots: DesyncedBot[];
}

function StatusBadge({ ok }: { ok: boolean }) {
  return (
    <span className={`inline-block px-3 py-1 rounded text-sm font-medium ${
      ok ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'
    }`}>
      {ok ? 'OK' : 'FAIL'}
    </span>
  );
}

export default function AdminHealthPage() {
  const { data: health, isLoading, isError, error, refetch, isFetching } = useQuery<AdminHealth>({
    queryKey: ['admin', 'health'],
    queryFn: async () => (await adminApi.getHealth()).data,
    retry: false,
    refetchInterval: 15000,
  });

  if (isError) {
    const status = (error as any)?.response?.status;
    return (
      <div className="min-h-screen bg-gray-900">
        <Navbar />
        <div className="max-w-2xl mx-auto px-4 py-16 text-center">
          <h1 className="text-2xl font-bold text-gray-300">
            {status === 403 ? 'Доступ запрещён' : 'Ошибка загрузки'}
          </h1>
        </div>
      </div>
    );
  }

  const desyncCount = health?.desynced_bots.length ?? 0;

  return (
    <div className="min-h-screen bg-gray-900">
      <Navbar />

      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-3xl font-bold">Health</h1>
          <div className="flex items-center gap-3">
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="px-3 py-1.5 rounded bg-gray-800 border border-gray-700 hover:bg-gray-700 text-sm disabled:opacity-50"
            >
              {isFetching ? 'Обновление...' : 'Обновить'}
            </button>
            <Link href="/admin" className="text-sm text-gray-400 hover:text-gray-200">← Admin</Link>
          </div>
        </div>

        {isLoading || !health ? (
          <p className="text-gray-400">Загрузка...</p>
        ) : (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-gray-400 text-sm">Redis</p>
                  <StatusBadge ok={health.redis_ok} />
                </div>
                {health.redis_error && (
                  <p className="text-red-400 text-xs mt-2 break-words">{health.redis_error}</p>
                )}
              </div>

              <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-gray-400 text-sm">Price Tracker</p>
                  <StatusBadge ok={health.price_tracker_ok} />
                </div>
                {health.price_tracker_error && (
                  <p className="text-red-400 text-xs mt-2 break-words">{health.price_tracker_error}</p>
                )}
              </div>
            </div>

            <div
              className={`bg-gray-800 rounded-lg border p-6 ${
                desyncCount > 0 ? 'border-amber-600' : 'border-gray-700'
              }`}
            >
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold">Регистрация ботов на прослушку цены</h2>
                <span className="text-sm text-gray-400">
                  В памяти: {health.registered_bots_count} / В БД активных: {health.db_active_bots_count}
                </span>
              </div>

              {desyncCount === 0 ? (
                <p className="text-green-400 text-sm">Расхождений нет — все активные боты зарегистрированы.</p>
              ) : (
                <>
                  <p className="text-amber-400 text-sm mb-3">
                    {desyncCount} бот(ов) в БД помечены как WAITING/PYRAMIDING, но не зарегистрированы в памяти —
                    они не получают тики цены и не сработают, пока не будут перерегистрированы.
                  </p>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-gray-400 border-b border-gray-700">
                        <th className="py-2 pr-4">Bot ID</th>
                        <th className="py-2 pr-4">Владелец</th>
                        <th className="py-2 pr-4">Символ</th>
                        <th className="py-2 pr-4">State</th>
                      </tr>
                    </thead>
                    <tbody>
                      {health.desynced_bots.map(b => (
                        <tr key={b.bot_id} className="border-b border-gray-700 last:border-0">
                          <td className="py-2 pr-4">{b.bot_id}</td>
                          <td className="py-2 pr-4">{b.owner_username}</td>
                          <td className="py-2 pr-4">{b.symbol}</td>
                          <td className="py-2 pr-4 text-amber-400">{b.state}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </div>

            <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
              <h2 className="text-lg font-semibold mb-4">Активные подписки Price Tracker</h2>
              {Object.keys(health.price_tracker_subscriptions).length === 0 ? (
                <p className="text-gray-500 text-sm">Нет активных подписок</p>
              ) : (
                Object.entries(health.price_tracker_subscriptions).map(([exchange, symbols]) => (
                  <div key={exchange} className="mb-3 last:mb-0">
                    <p className="text-gray-400 text-sm mb-1">{exchange}</p>
                    <div className="flex flex-wrap gap-2">
                      {symbols.map(s => (
                        <span key={s} className="px-2 py-1 bg-gray-900 border border-gray-700 rounded text-xs">
                          {s}
                        </span>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
