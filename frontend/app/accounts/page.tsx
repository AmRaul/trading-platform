'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { accountsApi } from '@/lib/api';
import Navbar from '@/components/Navbar';
import { Plus, Trash2, Pencil, Key } from 'lucide-react';

interface Account {
  id: number;
  name: string;
  webhook_url_hint: string;
  has_api_key: boolean;
  has_api_secret: boolean;
}

interface AccountForm {
  name: string;
  webhook_url: string;
  api_key: string;
  api_secret: string;
}

const emptyForm: AccountForm = { name: '', webhook_url: '', api_key: '', api_secret: '' };

export default function AccountsPage() {
  const queryClient = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [editAccount, setEditAccount] = useState<Account | null>(null);
  const [form, setForm] = useState<AccountForm>(emptyForm);

  const { data: accounts = [], isLoading } = useQuery<Account[]>({
    queryKey: ['accounts'],
    queryFn: async () => (await accountsApi.getAll()).data,
  });

  const createMutation = useMutation({
    mutationFn: (data: AccountForm) => accountsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] });
      closeModal();
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<AccountForm> }) =>
      accountsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] });
      closeModal();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => accountsApi.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['accounts'] }),
  });

  const openCreate = () => {
    setEditAccount(null);
    setForm(emptyForm);
    setShowModal(true);
  };

  const openEdit = (account: Account) => {
    setEditAccount(account);
    setForm({ name: account.name, webhook_url: '', api_key: '', api_secret: '' });
    setShowModal(true);
  };

  const closeModal = () => {
    setShowModal(false);
    setEditAccount(null);
    setForm(emptyForm);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editAccount) {
      const patch: Partial<AccountForm> = { name: form.name };
      if (form.webhook_url) patch.webhook_url = form.webhook_url;
      if (form.api_key) patch.api_key = form.api_key;
      if (form.api_secret) patch.api_secret = form.api_secret;
      updateMutation.mutate({ id: editAccount.id, data: patch });
    } else {
      createMutation.mutate(form);
    }
  };

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <Navbar />

      <div className="max-w-4xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-3xl font-bold">Cryptorg Accounts</h1>
          <button
            onClick={openCreate}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium transition-colors"
          >
            <Plus size={16} />
            Add Account
          </button>
        </div>

        {isLoading && (
          <p className="text-gray-400">Loading...</p>
        )}

        {!isLoading && accounts.length === 0 && (
          <div className="text-center py-16 text-gray-500">
            <Key size={48} className="mx-auto mb-4 opacity-30" />
            <p>No accounts yet — add your first Cryptorg account</p>
          </div>
        )}

        <div className="grid gap-4">
          {accounts.map((account) => (
            <div
              key={account.id}
              className="bg-gray-800 rounded-lg border border-gray-700 p-5 flex items-center justify-between"
            >
              <div>
                <p className="text-lg font-semibold">{account.name}</p>
                <p className="text-gray-400 text-sm mt-1">
                  Webhook: <span className="font-mono">{account.webhook_url_hint}</span>
                </p>
                <div className="flex gap-3 mt-2 text-xs text-gray-500">
                  <span className={account.has_api_key ? 'text-green-400' : ''}>
                    API Key: {account.has_api_key ? '✓' : '—'}
                  </span>
                  <span className={account.has_api_secret ? 'text-green-400' : ''}>
                    API Secret: {account.has_api_secret ? '✓' : '—'}
                  </span>
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => openEdit(account)}
                  className="p-2 rounded hover:bg-gray-700 text-gray-400 hover:text-white transition-colors"
                  title="Edit"
                >
                  <Pencil size={16} />
                </button>
                <button
                  onClick={() => deleteMutation.mutate(account.id)}
                  className="p-2 rounded hover:bg-red-900 text-gray-400 hover:text-red-400 transition-colors"
                  title="Delete"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {showModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-xl border border-gray-700 w-full max-w-md p-6">
            <h2 className="text-xl font-bold mb-5">
              {editAccount ? 'Edit Account' : 'Add Account'}
            </h2>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Name</label>
                <input
                  type="text"
                  required
                  placeholder="Main Account"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  Webhook URL{editAccount ? ' (leave blank to keep current)' : ''}
                </label>
                <input
                  type="text"
                  required={!editAccount}
                  placeholder="https://api2.cryptorg.net/webhook/..."
                  value={form.webhook_url}
                  onChange={(e) => setForm({ ...form, webhook_url: e.target.value })}
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  API Key (optional)
                </label>
                <input
                  type="password"
                  placeholder={editAccount && editAccount.has_api_key ? '••••••••' : 'API Key'}
                  value={form.api_key}
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  API Secret (optional)
                </label>
                <input
                  type="password"
                  placeholder={editAccount && editAccount.has_api_secret ? '••••••••' : 'API Secret'}
                  value={form.api_secret}
                  onChange={(e) => setForm({ ...form, api_secret: e.target.value })}
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                />
              </div>
              <div className="flex gap-3 pt-2">
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
                  {isPending ? 'Saving...' : editAccount ? 'Update' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
