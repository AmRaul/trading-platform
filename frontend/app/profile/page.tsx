'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { profileApi } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import Navbar from '@/components/Navbar';
import { Save, Key, CheckCircle, AlertCircle } from 'lucide-react';

export default function ProfilePage() {
  const { user } = useAuthStore();
  const queryClient = useQueryClient();

  const [form, setForm] = useState({
    exchange: 'cryptorg',
    webhook_url: '',
    api_key: '',
    api_secret: '',
  });
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  const { data: creds, isLoading } = useQuery({
    queryKey: ['credentials'],
    queryFn: async () => {
      const res = await profileApi.getCredentials();
      return res.data;
    },
  });

  const mutation = useMutation({
    mutationFn: (data: typeof form) => profileApi.saveCredentials(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] });
      setSaved(true);
      setError('');
      setTimeout(() => setSaved(false), 3000);
      setForm(f => ({ ...f, api_key: '', api_secret: '' }));
    },
    onError: (e: any) => {
      setError(e?.response?.data?.detail || 'Ошибка сохранения');
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.webhook_url.trim()) {
      setError('Webhook URL обязателен');
      return;
    }
    const payload: any = { exchange: form.exchange, webhook_url: form.webhook_url };
    if (form.api_key) payload.api_key = form.api_key;
    if (form.api_secret) payload.api_secret = form.api_secret;
    mutation.mutate(payload);
  };

  return (
    <div className="min-h-screen bg-gray-900">
      <Navbar />
      <div className="max-w-2xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold mb-6">Профиль</h1>

        {/* User info */}
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 mb-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-400">Пользователь</p>
              <p className="font-semibold">{user?.username}</p>
            </div>
            <div className="text-right">
              <p className="text-sm text-gray-400">Биржа</p>
              <p className="font-semibold text-blue-400">
                {isLoading ? '...' : (creds?.exchange || 'не настроена')}
              </p>
            </div>
          </div>
          {creds && (
            <div className="mt-3 pt-3 border-t border-gray-700 text-xs text-gray-500">
              <span>Webhook: {creds.webhook_url_hint}</span>
              {creds.has_api_key && <span className="ml-4">API Key: •••</span>}
            </div>
          )}
        </div>

        {/* Credentials form */}
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-5">
          <div className="flex items-center gap-2 mb-4">
            <Key size={18} className="text-blue-400" />
            <h2 className="font-semibold">API Ключи</h2>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Биржа</label>
              <select
                value={form.exchange}
                onChange={e => setForm(f => ({ ...f, exchange: e.target.value }))}
                className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
              >
                <option value="cryptorg">Cryptorg</option>
                <option value="bybit">Bybit</option>
                <option value="binance">Binance</option>
              </select>
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">Webhook URL *</label>
              <input
                type="text"
                value={form.webhook_url}
                onChange={e => setForm(f => ({ ...f, webhook_url: e.target.value }))}
                placeholder="https://api3.cryptorg.net/..."
                className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">API Key (опционально)</label>
              <input
                type="password"
                value={form.api_key}
                onChange={e => setForm(f => ({ ...f, api_key: e.target.value }))}
                placeholder="Оставьте пустым чтобы не менять"
                className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">API Secret (опционально)</label>
              <input
                type="password"
                value={form.api_secret}
                onChange={e => setForm(f => ({ ...f, api_secret: e.target.value }))}
                placeholder="Оставьте пустым чтобы не менять"
                className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
              />
            </div>

            {error && (
              <div className="flex items-center gap-2 text-red-400 text-sm">
                <AlertCircle size={16} />
                {error}
              </div>
            )}

            {saved && (
              <div className="flex items-center gap-2 text-green-400 text-sm">
                <CheckCircle size={16} />
                Сохранено
              </div>
            )}

            <button
              type="submit"
              disabled={mutation.isPending}
              className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium"
            >
              <Save size={16} />
              {mutation.isPending ? 'Сохранение...' : 'Сохранить'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
