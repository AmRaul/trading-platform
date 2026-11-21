'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { adminApi, meApi } from '@/lib/api';
import { apiErrorText } from '@/lib/types';
import Navbar from '@/components/Navbar';

interface AdminUserRow {
  id: number;
  username: string;
  email: string | null;
  is_active: boolean;
  approved: boolean;
  status: 'pending' | 'active' | 'blocked';
  telegram_linked: boolean;
  plan: string;
  created_at: string;
  bots_count: number;
  accounts_count: number;
}

const STATUS: Record<AdminUserRow['status'], { label: string; cls: string }> = {
  pending: { label: 'ждёт одобрения', cls: 'text-yellow-400' },
  active: { label: 'активен', cls: 'text-green-400' },
  blocked: { label: 'заблокирован', cls: 'text-red-400' },
};

type Action = 'approve' | 'block' | 'unblock' | 'reset';

export default function AdminUsersPage() {
  const qc = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const { data: users, isLoading, isError, error } = useQuery<AdminUserRow[]>({
    queryKey: ['admin', 'users'],
    queryFn: async () => (await adminApi.getUsers()).data,
    retry: false,
  });

  const { data: me } = useQuery({ queryKey: ['me'], queryFn: async () => (await meApi.get()).data });

  const act = useMutation({
    mutationFn: async ({ action, user }: { action: Action; user: AdminUserRow }) => {
      if (action === 'approve') return (await adminApi.approveUser(user.id)).data;
      if (action === 'block') return (await adminApi.blockUser(user.id)).data;
      if (action === 'unblock') return (await adminApi.unblockUser(user.id)).data;
      return (await adminApi.resetPassword(user.id)).data;
    },
    onSuccess: (data, { action, user }) => {
      qc.invalidateQueries({ queryKey: ['admin', 'users'] });
      if (action === 'reset' && 'temporary_password' in data) {
        setMessage(`Временный пароль для ${user.username}: ${data.temporary_password} — передайте его, `
          + 'пользователь сменит его в «Настройках». Больше он показан не будет.');
      } else {
        setMessage(null);
      }
    },
    onError: (e) => setMessage(apiErrorText(e)),
  });

  const run = (action: Action, user: AdminUserRow) => {
    if (action === 'block' && !confirm(`Закрыть доступ ${user.username}? Его боты продолжат работать.`)) return;
    if (action === 'reset' && !confirm(`Сбросить пароль ${user.username}? Его сессии на всех устройствах закроются.`)) return;
    act.mutate({ action, user });
  };

  if (isError) {
    const status = (error as { response?: { status?: number } })?.response?.status;
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

  const pending = users?.filter((u) => u.status === 'pending').length ?? 0;
  const btn = 'px-2 py-1 rounded text-xs disabled:opacity-50';

  return (
    <div className="min-h-screen bg-gray-900">
      <Navbar />

      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-3xl font-bold">
            Пользователи
            {pending > 0 && <span className="ml-3 text-base text-yellow-400">заявок: {pending}</span>}
          </h1>
          <Link href="/admin" className="text-sm text-gray-400 hover:text-gray-200">← Admin</Link>
        </div>

        {message && (
          <div className="mb-4 p-3 rounded bg-gray-800 border border-gray-600 text-sm break-all">{message}</div>
        )}

        {isLoading ? (
          <p className="text-gray-400">Загрузка...</p>
        ) : (
          <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-400 border-b border-gray-700">
                  <th className="px-4 py-3">ID</th>
                  <th className="px-4 py-3">Логин</th>
                  <th className="px-4 py-3">Статус</th>
                  <th className="px-4 py-3">Telegram</th>
                  <th className="px-4 py-3">Ботов</th>
                  <th className="px-4 py-3">Аккаунтов</th>
                  <th className="px-4 py-3">Регистрация</th>
                  <th className="px-4 py-3">Действия</th>
                </tr>
              </thead>
              <tbody>
                {users?.map((u) => (
                  <tr key={u.id} className="border-b border-gray-700 last:border-0">
                    <td className="px-4 py-3 text-gray-400">{u.id}</td>
                    <td className="px-4 py-3 font-medium">{u.username}</td>
                    <td className={`px-4 py-3 ${STATUS[u.status].cls}`}>{STATUS[u.status].label}</td>
                    <td className="px-4 py-3">{u.telegram_linked ? '✓' : '—'}</td>
                    <td className="px-4 py-3">{u.bots_count}</td>
                    <td className="px-4 py-3">{u.accounts_count}</td>
                    <td className="px-4 py-3 text-gray-400">{new Date(u.created_at).toLocaleString('ru-RU')}</td>
                    <td className="px-4 py-3">
                      {u.username === me?.username ? <span className="text-gray-500 text-xs">это вы</span> : (
                      <div className="flex flex-wrap gap-1">
                        {u.status === 'pending' && (
                          <button disabled={act.isPending} onClick={() => run('approve', u)}
                            className={`${btn} bg-green-700 hover:bg-green-600`}>Одобрить</button>
                        )}
                        {u.status === 'blocked' ? (
                          <button disabled={act.isPending} onClick={() => run('unblock', u)}
                            className={`${btn} bg-gray-700 hover:bg-gray-600`}>Разблокировать</button>
                        ) : (
                          <button disabled={act.isPending} onClick={() => run('block', u)}
                            className={`${btn} bg-gray-700 hover:bg-red-800`}>
                            {u.status === 'pending' ? 'Отклонить' : 'Заблокировать'}
                          </button>
                        )}
                        {u.status !== 'pending' && (
                          <button disabled={act.isPending} onClick={() => run('reset', u)}
                            className={`${btn} bg-gray-700 hover:bg-gray-600`}>Сбросить пароль</button>
                        )}
                      </div>
                      )}
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
