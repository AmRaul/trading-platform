'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { adminApi } from '@/lib/api';
import Navbar from '@/components/Navbar';

interface AdminBotRow {
  id: number;
  owner_username: string;
  name: string;
  symbol: string;
  side: string;
  state: string;
  is_active: boolean;
  total_pnl: number;
  created_at: string;
}

export default function AdminBotsPage() {
  const { data: bots, isLoading, isError, error } = useQuery<AdminBotRow[]>({
    queryKey: ['admin', 'bots'],
    queryFn: async () => (await adminApi.getBots()).data,
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
          <h1 className="text-3xl font-bold">Все боты</h1>
          <Link href="/admin" className="text-sm text-gray-400 hover:text-gray-200">← Admin</Link>
        </div>

        {isLoading ? (
          <p className="text-gray-400">Загрузка...</p>
        ) : (
          <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-400 border-b border-gray-700">
                  <th className="px-4 py-3">ID</th>
                  <th className="px-4 py-3">Владелец</th>
                  <th className="px-4 py-3">Имя</th>
                  <th className="px-4 py-3">Символ</th>
                  <th className="px-4 py-3">Side</th>
                  <th className="px-4 py-3">State</th>
                  <th className="px-4 py-3">Активен</th>
                  <th className="px-4 py-3">Total PnL</th>
                  <th className="px-4 py-3">Создан</th>
                </tr>
              </thead>
              <tbody>
                {bots?.map(b => (
                  <tr key={b.id} className="border-b border-gray-700 last:border-0">
                    <td className="px-4 py-3 text-gray-400">{b.id}</td>
                    <td className="px-4 py-3 font-medium">{b.owner_username}</td>
                    <td className="px-4 py-3">{b.name}</td>
                    <td className="px-4 py-3">{b.symbol}</td>
                    <td className="px-4 py-3">
                      <span className={b.side === 'LONG' ? 'text-green-400' : 'text-red-400'}>{b.side}</span>
                    </td>
                    <td className="px-4 py-3 text-gray-400">{b.state}</td>
                    <td className="px-4 py-3">
                      <span className={b.is_active ? 'text-green-400' : 'text-gray-500'}>
                        {b.is_active ? 'да' : 'нет'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={b.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                        {b.total_pnl.toFixed(2)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-400">
                      {new Date(b.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
                {bots?.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-4 py-8 text-center text-gray-500">Нет ботов</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
