'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { botsApi, accountsApi, bybitAccountsApi } from '@/lib/api';
import {
  apiErrorText,
  type BotPayload, type BotSide, type BotType, type BybitAccount, type CryptorgAccount, type EntrySignal, type Exchange,
} from '@/lib/types';
import EntrySignalFields from './EntrySignalFields';
import StraddleFields, { STRADDLE_DEFAULTS, toStraddle } from './StraddleFields';

export default function CreateBotModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [exchange, setExchange] = useState<Exchange>('cryptorg');
  const [accountId, setAccountId] = useState<number | null>(null);
  const [bybitAccountId, setBybitAccountId] = useState<number | null>(null);
  const [formData, setFormData] = useState({
    name: '',
    symbol: 'BTCUSDT',
    side: 'LONG' as BotSide,
    bot_type: 'pyramiding' as BotType,
    order_count: 4,
    entry_size_usdt: 10.0,
    step_percent: 4,
    leverage: 10,
    pyramiding_multiplier: 1.5,
    dca_multiplier: 1.0,
    dca_multiplier_price: 1.0,
    sl_enabled: true,
    sl_initial: 5,
    sl_breakeven_plus: 0.5,
    tp_percent: 3,
    sl_after_order3: 2,
    use_trailing: true,
    trailing_percent: 1.5,
    sl_breakeven_on_order2: true,
    cycle: false,
    entry_signal: null as EntrySignal | null,
    ...STRADDLE_DEFAULTS,
  });

  const { data: accounts = [] } = useQuery<CryptorgAccount[]>({
    queryKey: ['accounts'],
    queryFn: async () => (await accountsApi.getAll()).data,
  });

  const { data: bybitAccounts = [] } = useQuery<BybitAccount[]>({
    queryKey: ['bybit-accounts'],
    queryFn: async () => (await bybitAccountsApi.getAll()).data,
  });

  const createMutation = useMutation({
    mutationFn: (data: BotPayload) => botsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bots'] });
      onClose();
    },
  });

  const errorMessage = createMutation.error ? apiErrorText(createMutation.error, 'Failed to create bot') : null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const { name, symbol, side, sl_enabled, ...rest } = formData;
    const config = { ...rest, sl_initial: sl_enabled ? rest.sl_initial : null };
    createMutation.mutate({
      name, symbol, side, config,
      exchange,
      account_id: exchange === 'cryptorg' ? accountId : null,
      bybit_account_id: exchange === 'bybit' ? bybitAccountId : null,
    });
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center p-3 z-50">
      <div className="bg-gray-800 rounded-lg max-w-xl w-full max-h-[90vh] overflow-y-auto p-4">
        <h2 className="text-base font-bold mb-3">Создать бота</h2>

        <form onSubmit={handleSubmit} className="space-y-3">
          {/* Bot type toggle */}
          <div className="flex rounded overflow-hidden border border-gray-600">
            <button
              type="button"
              onClick={() => setFormData({ ...formData, bot_type: 'pyramiding', side: formData.side === 'NEUTRAL' ? 'LONG' : formData.side })}
              className={`flex-1 py-1.5 text-xs font-medium transition-colors ${
                formData.bot_type === 'pyramiding' ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
              }`}
            >
              Пирамидинг
            </button>
            <button
              type="button"
              onClick={() => setFormData({ ...formData, bot_type: 'dca', side: formData.side === 'NEUTRAL' ? 'LONG' : formData.side })}
              className={`flex-1 py-1.5 text-xs font-medium transition-colors ${
                formData.bot_type === 'dca' ? 'bg-orange-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
              }`}
            >
              DCA
            </button>
            <button type="button"
              onClick={() => setFormData(toStraddle(formData))}
              className={`flex-1 py-1.5 text-xs font-medium transition-colors ${formData.bot_type === 'straddle' ? 'bg-purple-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'}`}>
              Straddle
            </button>
          </div>

          <p className="text-xs text-gray-500">
            {formData.bot_type === 'pyramiding'
              ? 'Добавляет ордера когда цена идёт в нашу сторону.'
              : formData.bot_type === 'straddle'
                ? 'При запуске открывает LONG и SHORT. Сторона, куда пошла цена, добирает каждый шаг, вторая не добирает и страхует. Возврат к точке запуска — доборы закрываются; ушли на N шагов — минусовая закрывается, дальше трейлинг.'
                : 'Cryptorg ставит лимитки ниже рынка, усредняет позицию.'}
          </p>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Название</label>
              <input type="text" value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" required />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">Символ</label>
              <input type="text" value={formData.symbol}
                onChange={(e) => setFormData({ ...formData, symbol: e.target.value })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" required />
            </div>

            <div className="col-span-2">
              <label className="block text-xs text-gray-400 mb-1">Биржа</label>
              <div className="flex rounded overflow-hidden border border-gray-600">
                <button type="button"
                  onClick={() => setExchange('cryptorg')}
                  className={`flex-1 py-1.5 text-xs font-medium transition-colors ${exchange === 'cryptorg' ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'}`}>
                  Cryptorg
                </button>
                <button type="button"
                  onClick={() => setExchange('bybit')}
                  className={`flex-1 py-1.5 text-xs font-medium transition-colors ${exchange === 'bybit' ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'}`}>
                  Bybit
                </button>
                <button type="button"
                  onClick={() => setExchange('paper')}
                  className={`flex-1 py-1.5 text-xs font-medium transition-colors ${exchange === 'paper' ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'}`}>
                  Бумажный
                </button>
              </div>
            </div>

            {exchange === 'cryptorg' ? (
              <div className="col-span-2">
                <label className="block text-xs text-gray-400 mb-1">Аккаунт Cryptorg</label>
                <select
                  value={accountId ?? ''}
                  onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : null)}
                  className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                >
                  <option value="">— Без аккаунта —</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.name} ({a.webhook_url_hint})</option>
                  ))}
                </select>
              </div>
            ) : exchange === 'bybit' ? (
              <div className="col-span-2">
                <label className="block text-xs text-gray-400 mb-1">Аккаунт Bybit</label>
                <select
                  value={bybitAccountId ?? ''}
                  onChange={(e) => setBybitAccountId(e.target.value ? Number(e.target.value) : null)}
                  className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                  required
                >
                  <option value="">— Выберите аккаунт —</option>
                  {bybitAccounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.name} ({a.api_key_hint}){a.testnet ? ' — testnet' : ''}</option>
                  ))}
                </select>
              </div>
            ) : (
              <p className="col-span-2 text-xs text-gray-400">
                Бумажный режим: ордера не уходят на биржу, исполнение по живой цене Bybit, комиссия 0.055% вычитается из PnL.
              </p>
            )}

            {formData.bot_type === 'straddle' ? (
            <div>
              <label className="block text-xs text-gray-400 mb-1">Сторона</label>
              <div className="px-2 py-1.5 text-sm bg-gray-700/50 border border-gray-600 rounded text-gray-300">LONG + SHORT</div>
            </div>
            ) : (
            <div>
              <label className="block text-xs text-gray-400 mb-1">Сторона</label>
              <select value={formData.side}
                onChange={(e) => setFormData({ ...formData, side: e.target.value as BotSide })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded">
                <option value="LONG">LONG</option>
                <option value="SHORT">SHORT</option>
              </select>
            </div>
            )}

            <div>
              <label className="block text-xs text-gray-400 mb-1">Плечо</label>
              <input type="number" value={formData.leverage}
                onChange={(e) => setFormData({ ...formData, leverage: parseInt(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                min="1" max="125" />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">Размер входа (USDT)</label>
              <input type="number" value={formData.entry_size_usdt}
                onChange={(e) => setFormData({ ...formData, entry_size_usdt: parseFloat(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                min="1" step="0.1" />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">
                Шаг % {formData.bot_type === 'dca' ? '(усреднение ↓)' : formData.bot_type === 'straddle' ? '(уровни от точки запуска)' : '(триггер ↑)'}
              </label>
              <input type="number" value={formData.step_percent}
                onChange={(e) => setFormData({ ...formData, step_percent: parseFloat(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" step="0.1" />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">{formData.bot_type === 'straddle' ? 'Ордеров рабочей стороны (со входом)' : 'Кол-во ордеров (со входом)'}</label>
              <input type="number" value={formData.order_count}
                onChange={(e) => setFormData({ ...formData, order_count: parseInt(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                min="1" max="10" />
            </div>

            {formData.bot_type !== 'dca' ? (
              <div>
                <label className="block text-xs text-gray-400 mb-1">Мультипликатор пир.</label>
                <input type="number" value={formData.pyramiding_multiplier}
                  onChange={(e) => setFormData({ ...formData, pyramiding_multiplier: parseFloat(e.target.value) })}
                  className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                  step="0.1" min="0.1" max="3" />
              </div>
            ) : (
              <>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">DCA мульт. объёма</label>
                  <input type="number" value={formData.dca_multiplier}
                    onChange={(e) => setFormData({ ...formData, dca_multiplier: parseFloat(e.target.value) })}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                    step="0.1" min="1" />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">DCA мульт. шага цены</label>
                  <input type="number" value={formData.dca_multiplier_price}
                    onChange={(e) => setFormData({ ...formData, dca_multiplier_price: parseFloat(e.target.value) })}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                    step="0.1" min="1" />
                </div>
              </>
            )}

            {formData.bot_type === 'straddle' ? (
              <StraddleFields value={formData} onChange={(v) => setFormData({ ...formData, ...v })} />
            ) : (
            <>
            <div>
              <label className="block text-xs text-gray-400 mb-1">
                <span className="flex items-center gap-1.5">
                  <input type="checkbox" checked={formData.sl_enabled}
                    onChange={(e) => setFormData({ ...formData, sl_enabled: e.target.checked })} />
                  Стоп-лосс на вход (%)
                </span>
              </label>
              <input type="number" value={formData.sl_initial}
                onChange={(e) => setFormData({ ...formData, sl_initial: parseFloat(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded disabled:opacity-40"
                step="0.1" disabled={!formData.sl_enabled} />
              <p className="text-[11px] text-gray-500 mt-1">
                Защищает только 1–2 ордер. SL после 3 ордера и трейлинг ниже работают независимо и не выключаются этим чекбоксом.
              </p>
            </div>

            </>
            )}

            <div>
              <label className="block text-xs text-gray-400 mb-1">
                Тейк-профит (%){formData.bot_type === 'straddle' ? ' · 100 — без тейка' : ''}
              </label>
              <input type="number" value={formData.tp_percent}
                onChange={(e) => setFormData({ ...formData, tp_percent: parseFloat(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                step="0.1" min="0.1" />
            </div>

            {formData.bot_type === 'pyramiding' && (
              <>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">SL безубыток + (%)</label>
                  <input type="number" value={formData.sl_breakeven_plus}
                    onChange={(e) => setFormData({ ...formData, sl_breakeven_plus: parseFloat(e.target.value) })}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                    step="0.1" min="0" />
                </div>

                <div>
                  <label className="block text-xs text-gray-400 mb-1">SL после ордера 3 (%)</label>
                  <input type="number" value={formData.sl_after_order3}
                    onChange={(e) => setFormData({ ...formData, sl_after_order3: parseFloat(e.target.value) })}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" step="0.1" />
                </div>
              </>
            )}

            <div>
              <label className="block text-xs text-gray-400 mb-1">Трейлинг (%)</label>
              <input type="number" value={formData.trailing_percent}
                onChange={(e) => setFormData({ ...formData, trailing_percent: parseFloat(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded" step="0.1" />
            </div>

            <div className="flex items-center">
              <label className="flex items-center gap-1.5 cursor-pointer text-xs">
                <input type="checkbox" checked={formData.use_trailing}
                  onChange={(e) => setFormData({ ...formData, use_trailing: e.target.checked })} />
                Трейлинг стоп
              </label>
            </div>

            <div className="flex items-center">
              <label className="flex items-center gap-1.5 cursor-pointer text-xs">
                <input type="checkbox" checked={formData.cycle}
                  onChange={(e) => setFormData({ ...formData, cycle: e.target.checked })} />
                Цикл (авто-перезапуск)
              </label>
            </div>

            {formData.bot_type === 'pyramiding' && (
              <div className="flex items-center">
                <label className="flex items-center gap-1.5 cursor-pointer text-xs">
                  <input type="checkbox" checked={formData.sl_breakeven_on_order2}
                    onChange={(e) => setFormData({ ...formData, sl_breakeven_on_order2: e.target.checked })} />
                  SL в безубыток на ордере 2
                </label>
              </div>
            )}

            {formData.bot_type !== 'straddle' && (
            <EntrySignalFields
              value={formData.entry_signal}
              onChange={(entry_signal) => setFormData({ ...formData, entry_signal })}
            />
            )}
          </div>

          {errorMessage && (
            <div className="text-red-400 text-xs bg-red-900/30 border border-red-700 rounded px-2 py-1.5">
              {errorMessage}
            </div>
          )}

          <div className="flex gap-2 pt-2">
            <button type="submit"
              className="flex-1 px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 rounded"
              disabled={createMutation.isPending}>
              {createMutation.isPending ? 'Создание...' : 'Создать'}
            </button>
            <button type="button" onClick={onClose}
              className="px-3 py-1.5 text-sm bg-gray-700 hover:bg-gray-600 rounded">
              Отмена
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
