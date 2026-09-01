'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { bybitAccountsApi } from '@/lib/api';
import Navbar from '@/components/Navbar';
import { Plus, Trash2, Pencil, Key } from 'lucide-react';

interface BybitAccount {
  id: number;
  name: string;
  api_key_hint: string;
  testnet: boolean;
}

interface BybitAccountForm {
  name: string;
  api_key: string;
  api_secret: string;
  testnet: boolean;
}

const emptyForm: BybitAccountForm = { name: '', api_key: '', api_secret: '', testnet: false };

export default function BybitAccountsPage() {
  const queryClient = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [editAccount, setEditAccount] = useState<BybitAccount | null>(null);
  const [form, setForm] = useState<BybitAccountForm>(emptyForm);

  const { data: accounts = [], isLoading } = useQuery<BybitAccount[]>({
    queryKey: ['bybit-accounts'],
    queryFn: async () => (await bybitAccountsApi.getAll()).data,
  });

  const createMutation = useMutation({
    mutationFn: (data: BybitAccountForm) => bybitAccountsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bybit-accounts'] });
      closeModal();
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<BybitAccountForm> }) =>
      bybitAccountsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bybit-accounts'] });
      closeModal();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => bybitAccountsApi.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bybit-accounts'] }),
  });

  const openCreate = () => {
    setEditAccount(null);
    setForm(emptyForm);
    setShowModal(true);
  };

  const openEdit = (account: BybitAccount) => {
    setEditAccount(account);
    setForm({ name: account.name, api_key: '', api_secret: '', testnet: account.testnet });
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
      const patch: Partial<BybitAccountForm> = { name: form.name, testnet: form.testnet };
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
          <h1 className="text-3xl font-bold">Bybit Accounts</h1>
          <button
            onClick={openCreate}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium transition-colors"
          >
            <Plus size={16} />
            Add Account
          </button>
        </div>

        <p className="text-gray-500 text-sm mb-6">
          Боты с этим аккаунтом торгуют напрямую через Bybit API (не через Cryptorg webhook).
          Ключи хранятся в зашифрованном виде и никогда не показываются целиком после сохранения.
        </p>

        {isLoading && (
          <p className="text-gray-400">Loading...</p>
        )}

        {!isLoading && accounts.length === 0 && (
          <div className="text-center py-16 text-gray-500">
            <Key size={48} className="mx-auto mb-4 opacity-30" />
            <p>No Bybit accounts yet — add your API key/secret pair</p>
          </div>
        )}

        <div className="grid gap-4">
          {accounts.map((account) => (
            <div
              key={account.id}
              className="bg-gray-800 rounded-lg border border-gray-700 p-5 flex items-center justify-between"
            >
              <div>
                <div className="flex items-center gap-2">
                  <p className="text-lg font-semibold">{account.name}</p>
                  {account.testnet && (
                    <span className="px-2 py-0.5 rounded text-xs font-medium bg-amber-900 text-amber-300">
                      TESTNET
                    </span>
                  )}
                </div>
                <p className="text-gray-400 text-sm mt-1">
                  API Key: <span className="font-mono">{account.api_key_hint}</span>
                </p>
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
                  placeholder="Main Bybit Account"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  API Key{editAccount ? ' (leave blank to keep current)' : ''}
                </label>
                <input
                  type="password"
                  required={!editAccount}
                  placeholder={editAccount ? '••••••••' : 'API Key'}
                  value={form.api_key}
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  API Secret{editAccount ? ' (leave blank to keep current)' : ''}
                </label>
                <input
                  type="password"
                  required={!editAccount}
                  placeholder={editAccount ? '••••••••' : 'API Secret'}
                  value={form.api_secret}
                  onChange={(e) => setForm({ ...form, api_secret: e.target.value })}
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                />
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-400">
                <input
                  type="checkbox"
                  checked={form.testnet}
                  onChange={(e) => setForm({ ...form, testnet: e.target.checked })}
                  className="rounded"
                />
                Testnet (для проверки перед реальными деньгами)
              </label>
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
