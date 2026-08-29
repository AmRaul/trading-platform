'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { adminApi } from '@/lib/api';
import Navbar from '@/components/Navbar';

interface AdminStats {
  users_total: number;
  accounts_total: number;
  bots_total: number;
  bots_active: number;
  positions_open: number;
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
      <p className="text-gray-400 text-sm">{label}</p>
      <p className="text-3xl font-bold mt-2">{value}</p>
    </div>
  );
}

export default function AdminPage() {
  const { data: stats, isLoading, isError, error } = useQuery<AdminStats>({
    queryKey: ['admin', 'stats'],
    queryFn: async () => (await adminApi.getStats()).data,
    retry: false,
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

  return (
    <div className="min-h-screen bg-gray-900">
      <Navbar />

      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-3xl font-bold">Admin</h1>
          <div className="flex gap-3 text-sm">
            <Link href="/admin/users" className="px-3 py-1.5 rounded bg-gray-800 border border-gray-700 hover:bg-gray-700">
              Пользователи
            </Link>
            <Link href="/admin/bots" className="px-3 py-1.5 rounded bg-gray-800 border border-gray-700 hover:bg-gray-700">
              Все боты
            </Link>
            <Link href="/admin/health" className="px-3 py-1.5 rounded bg-gray-800 border border-gray-700 hover:bg-gray-700">
              Health
            </Link>
          </div>
        </div>

        {isLoading || !stats ? (
          <p className="text-gray-400">Загрузка...</p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <StatCard label="Пользователей" value={stats.users_total} />
            <StatCard label="Cryptorg аккаунтов" value={stats.accounts_total} />
            <StatCard label="Ботов всего" value={stats.bots_total} />
            <StatCard label="Ботов активно" value={stats.bots_active} />
            <StatCard label="Открытых позиций" value={stats.positions_open} />
          </div>
        )}
      </div>
    </div>
  );
}
