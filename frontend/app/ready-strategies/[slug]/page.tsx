'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  BarChart,
  Bar,
  Cell,
} from 'recharts';
import { readyStrategiesApi, accountsApi, bybitAccountsApi } from '@/lib/api';
import Navbar from '@/components/Navbar';
import { ArrowLeft, Play, AlertTriangle, X } from 'lucide-react';

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'up' | 'down' }) {
  return (
    <div className="bg-gray-800 p-4 rounded-lg border border-gray-700">
      <p className="text-gray-400 text-xs">{label}</p>
      <p
        className={`text-2xl font-bold mt-1 ${
          tone === 'up' ? 'text-green-500' : tone === 'down' ? 'text-red-500' : ''
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function RuleList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="bg-gray-800 p-6 rounded-lg border border-gray-700">
      <h3 className="font-semibold mb-3">{title}</h3>
      <ul className="space-y-2 text-sm text-gray-300 list-disc pl-5">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

const signed = (v: number) => `${v >= 0 ? '+' : ''}${v}%`;

function LaunchModal({ strategy, variant, onClose }: { strategy: any; variant: any; onClose: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [exchange, setExchange] = useState<'bybit' | 'cryptorg'>('bybit');
  const [accountId, setAccountId] = useState<number | null>(null);
  const [deposit, setDeposit] = useState('');

  const { data: bybitAccounts = [] } = useQuery<any[]>({
    queryKey: ['bybit-accounts'],
    queryFn: async () => (await bybitAccountsApi.getAll()).data,
  });
  const { data: cryptorgAccounts = [] } = useQuery<any[]>({
    queryKey: ['accounts'],
    queryFn: async () => (await accountsApi.getAll()).data,
  });
  const accounts = exchange === 'bybit' ? bybitAccounts : cryptorgAccounts;

  const preset = variant.bot_preset;
  const depositNum = parseFloat(deposit) || 0;
  const firstOrder = Math.round(depositNum * variant.first_order_pct_of_deposit) / 100;
  const gridUnits = Array.from({ length: preset.order_count }, (_, i) => Math.pow(preset.dca_multiplier, i))
    .reduce((a, b) => a + b, 0);
  const gridTotal = firstOrder * gridUnits;
  const gridMargin = gridTotal / preset.leverage;

  const launch = useMutation({
    mutationFn: () =>
      readyStrategiesApi.launch(strategy.slug, {
        variant_key: variant.key,
        deposit_usdt: depositNum,
        exchange,
        account_id: exchange === 'cryptorg' ? accountId : null,
        bybit_account_id: exchange === 'bybit' ? accountId : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bots'] });
      router.push('/bots');
    },
  });
  const error = (launch.error as any)?.response?.data?.detail;

  const canLaunch = depositNum > 0 && firstOrder >= 10 && accountId !== null && !launch.isPending;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center p-4 z-50">
      <div className="bg-gray-800 rounded-lg border border-gray-700 w-full max-w-md p-6">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-xl font-semibold">Запуск стратегии</h2>
            <p className="text-sm text-gray-400">{strategy.name} · {variant.name}</p>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-700" aria-label="Закрыть">
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-xs text-gray-400 mb-1">Биржа</label>
            <div className="flex rounded overflow-hidden border border-gray-600">
              {(['bybit', 'cryptorg'] as const).map((ex) => (
                <button
                  key={ex}
                  type="button"
                  onClick={() => { setExchange(ex); setAccountId(null); }}
                  className={`flex-1 py-1.5 text-sm ${exchange === ex ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}
                >
                  {ex === 'bybit' ? 'Bybit' : 'Cryptorg'}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">Аккаунт</label>
            {accounts.length === 0 ? (
              <p className="text-sm text-yellow-300">
                Нет аккаунтов {exchange === 'bybit' ? 'Bybit' : 'Cryptorg'} —{' '}
                <Link href={exchange === 'bybit' ? '/bybit-accounts' : '/accounts'} className="underline">добавьте аккаунт</Link>
              </p>
            ) : (
              <select
                value={accountId ?? ''}
                onChange={(e) => setAccountId(e.target.value ? parseInt(e.target.value) : null)}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
              >
                <option value="">Выберите аккаунт</option>
                {accounts.map((a: any) => (
                  <option key={a.id} value={a.id}>
                    {a.name}{a.testnet ? ' (testnet)' : ''}
                  </option>
                ))}
              </select>
            )}
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">Депозит под стратегию, USDT</label>
            <input
              type="number"
              min="0"
              step="100"
              value={deposit}
              onChange={(e) => setDeposit(e.target.value)}
              placeholder="например, 5700"
              className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
            />
          </div>

          {depositNum > 0 && (
            <div className="bg-gray-900 rounded p-3 text-sm space-y-1">
              <div className="flex justify-between">
                <span className="text-gray-400">Первый ордер ({variant.first_order_pct_of_deposit}%)</span>
                <span className={firstOrder < 10 ? 'text-red-400' : ''}>${firstOrder.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Вся сетка ({preset.order_count} ордеров, объём)</span>
                <span>${gridTotal.toFixed(0)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Маржа всей сетки ({preset.leverage}x)</span>
                <span>${gridMargin.toFixed(0)}</span>
              </div>
              {firstOrder < 10 && <p className="text-red-400 text-xs">Минимальный первый ордер — 10 USDT</p>}
            </div>
          )}

          <p className="text-xs text-gray-500">
            Бот будет создан и сразу перейдёт в ожидание сигнала MRC. Позиция откроется автоматически на
            закрытии 15-минутной свечи, когда сработает сигнал. Результаты на истории не гарантируют доходность.
          </p>

          {error && <p className="text-sm text-red-400">{typeof error === 'string' ? error : 'Не удалось запустить'}</p>}

          <button
            onClick={() => launch.mutate()}
            disabled={!canLaunch}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg font-medium bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:text-gray-400 disabled:cursor-not-allowed"
          >
            <Play size={16} /> {launch.isPending ? 'Запуск…' : 'Запустить'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ReadyStrategyPage() {
  const { slug } = useParams<{ slug: string }>();
  const { data: s, isLoading, isError } = useQuery({
    queryKey: ['ready-strategy', slug],
    queryFn: async () => (await readyStrategiesApi.getOne(slug)).data,
  });

  const [variantKey, setVariantKey] = useState<string | null>(null);
  const [launchOpen, setLaunchOpen] = useState(false);
  const variant = s?.variants.find((v: any) => v.key === variantKey) ?? s?.variants[0];
  const bt = variant?.backtest;
  const m = bt?.metrics;

  return (
    <div className="min-h-screen bg-gray-900">
      <Navbar />

      <div className="max-w-7xl mx-auto px-4 py-8">
        <Link href="/ready-strategies" className="inline-flex items-center gap-1 text-sm text-gray-400 hover:text-white mb-6">
          <ArrowLeft size={16} /> Все стратегии
        </Link>

        {isLoading && <p className="text-gray-400">Загрузка…</p>}
        {isError && <p className="text-red-400">Стратегия не найдена</p>}

        {s && (
          <>
            <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4 mb-6">
              <div>
                <h1 className="text-3xl font-bold">{s.name}</h1>
                <p className="text-gray-500 text-sm mt-1">
                  {s.symbol} · {s.side} · {s.timeframe}
                </p>
              </div>
              <button
                onClick={() => setLaunchOpen(true)}
                disabled={!s.launch_available}
                title={s.launch_available ? undefined : 'Запуск пока недоступен'}
                className="flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg font-medium bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:text-gray-400 disabled:cursor-not-allowed"
              >
                <Play size={18} /> Запустить · {variant.name}
              </button>
            </div>

            <p className="text-gray-300 mb-8 max-w-4xl">{s.description}</p>

            {!s.launch_available && s.launch_blockers.length > 0 && (
              <div className="bg-yellow-900/30 border border-yellow-800 rounded-lg p-4 mb-8">
                <p className="flex items-center gap-2 font-semibold text-yellow-300 mb-2">
                  <AlertTriangle size={18} /> Запуск пока недоступен
                </p>
                <ul className="text-sm text-yellow-100/80 list-disc pl-5 space-y-1">
                  {s.launch_blockers.map((b: string) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              </div>
            )}

            {s.variants.length > 1 && (
              <div className="mb-6">
                <h2 className="text-xl font-semibold mb-3">Вариант риска</h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-3xl">
                  {s.variants.map((v: any) => {
                    const active = v.key === variant.key;
                    const vm = v.backtest.metrics;
                    return (
                      <button
                        key={v.key}
                        onClick={() => setVariantKey(v.key)}
                        className={`text-left p-4 rounded-lg border transition-colors ${
                          active ? 'border-blue-500 bg-blue-950/40' : 'border-gray-700 bg-gray-800 hover:border-gray-500'
                        }`}
                      >
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="font-semibold">{v.name}</span>
                          <span className="text-green-500 font-semibold">≈{signed(vm.avg_annual_return_pct)} в год</span>
                        </div>
                        <p className="text-xs text-gray-400 mt-1">Просадка до {vm.max_drawdown_pct}% · первый ордер ≈{v.first_order_pct_of_deposit}% депозита</p>
                        <p className="text-xs text-gray-500 mt-2">{v.description}</p>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {m && (
              <>
                <h2 className="text-xl font-semibold mb-1">Бэктест · {variant.name}</h2>
                <p className="text-sm text-gray-500 mb-4">
                  {bt.period.start} — {bt.period.end} · депозит ${bt.params.deposit} · первый ордер ${bt.params.first_order}
                </p>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                  <Stat label="Доходность за период" value={signed(m.total_return_pct)} tone={m.total_return_pct >= 0 ? 'up' : 'down'} />
                  <Stat label="В среднем за год" value={signed(m.avg_annual_return_pct)} />
                  <Stat label="Макс. просадка" value={`${m.max_drawdown_pct}%`} tone="down" />
                  <Stat label="Сделок / стопов" value={`${m.trades} / ${m.stops}`} />
                  <Stat label="2021–2023" value={signed(m.period_2021_2023_pct)} />
                  <Stat label="2024–2026" value={signed(m.period_2024_2026_pct)} />
                  <Stat label="Полная сетка" value={`${m.full_grid_fills} раз`} />
                  <Stat label="Самая долгая сделка" value={`${m.max_trade_days} дн.`} />
                </div>

                <div className="bg-gray-800 p-6 rounded-lg border border-gray-700 mb-6">
                  <h3 className="font-semibold mb-4">Equity (с учётом плавающего PnL)</h3>
                  <div className="h-72">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={bt.equity_curve}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                        <XAxis dataKey="date" stroke="#9CA3AF" tick={{ fontSize: 12 }} minTickGap={40} />
                        <YAxis stroke="#9CA3AF" tick={{ fontSize: 12 }} domain={['auto', 'auto']} tickFormatter={(v) => `$${v}`} />
                        <Tooltip
                          contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                          formatter={(v: number, name: string) =>
                            name === 'equity' ? [`$${v.toFixed(0)}`, 'Equity'] : [`${v.toFixed(1)}%`, 'Просадка']
                          }
                        />
                        <Area type="monotone" dataKey="equity" stroke="#3B82F6" fill="#3B82F6" fillOpacity={0.15} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                <div className="bg-gray-800 p-6 rounded-lg border border-gray-700 mb-8">
                  <h3 className="font-semibold mb-4">Доходность по годам, % депозита</h3>
                  <div className="h-56">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={bt.yearly}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                        <XAxis dataKey="year" stroke="#9CA3AF" tick={{ fontSize: 12 }} />
                        <YAxis stroke="#9CA3AF" tick={{ fontSize: 12 }} tickFormatter={(v) => `${v}%`} />
                        <Tooltip
                          contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                          formatter={(v: number) => [`${v}%`, 'Доходность']}
                        />
                        <Bar dataKey="return_pct">
                          {bt.yearly.map((y: any) => (
                            <Cell key={y.year} fill={y.return_pct >= 0 ? '#22C55E' : '#EF4444'} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <RuleList title="Вход" items={s.entry_rules} />
              <RuleList title="Сопровождение и выход" items={s.exit_rules} />
              <RuleList title="Риски" items={s.risk_notes} />
              <RuleList title="Условия бэктеста" items={s.backtest_assumptions} />
            </div>

            {launchOpen && <LaunchModal strategy={s} variant={variant} onClose={() => setLaunchOpen(false)} />}

            <p className="text-xs text-gray-500 mt-8">
              Результаты на истории не гарантируют доходность в будущем. Торговля с плечом может привести к потере депозита.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
