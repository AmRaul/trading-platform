'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { adminApi } from '@/lib/api';
import Navbar from '@/components/Navbar';

interface AdminUserRow {
  id: number;
  username: string;
  email: string | null;
  is_active: boolean;
  plan: string;
  created_at: string;
  bots_count: number;
  accounts_count: number;
}

export default function AdminUsersPage() {
  const { data: users, isLoading, isError, error } = useQuery<AdminUserRow[]>({
    queryKey: ['admin', 'users'],
    queryFn: async () => (await adminApi.getUsers()).data,
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
          <h1 className="text-3xl font-bold">Пользователи</h1>
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
                  <th className="px-4 py-3">Username</th>
                  <th className="px-4 py-3">Email</th>
                  <th className="px-4 py-3">Plan</th>
                  <th className="px-4 py-3">Активен</th>
                  <th className="px-4 py-3">Ботов</th>
                  <th className="px-4 py-3">Аккаунтов</th>
                  <th className="px-4 py-3">Регистрация</th>
                </tr>
              </thead>
              <tbody>
                {users?.map(u => (
                  <tr key={u.id} className="border-b border-gray-700 last:border-0">
                    <td className="px-4 py-3 text-gray-400">{u.id}</td>
                    <td className="px-4 py-3 font-medium">{u.username}</td>
                    <td className="px-4 py-3 text-gray-400">{u.email || '—'}</td>
                    <td className="px-4 py-3">{u.plan}</td>
                    <td className="px-4 py-3">
                      <span className={u.is_active ? 'text-green-400' : 'text-gray-500'}>
                        {u.is_active ? 'да' : 'нет'}
                      </span>
                    </td>
                    <td className="px-4 py-3">{u.bots_count}</td>
                    <td className="px-4 py-3">{u.accounts_count}</td>
                    <td className="px-4 py-3 text-gray-400">
                      {new Date(u.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
                {users?.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-gray-500">Нет пользователей</td>
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
