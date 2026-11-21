'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import Navbar from '@/components/Navbar';
import { accountsApi, type AccountExchange } from '@/lib/api';
import { apiErrorText } from '@/lib/types';

const PERIODS = [7, 30, 90];

function num(x: number | null | undefined) {
  if (x == null) return '—';
  const digits = Math.abs(x) >= 100 ? 2 : Math.abs(x) >= 1 ? 4 : 6;
  return x.toLocaleString('ru-RU', { maximumFractionDigits: digits });
}

function money(x: number) {
  return <span className={x >= 0 ? 'text-green-400' : 'text-red-400'}>{x >= 0 ? '+' : ''}{x.toFixed(2)}$</span>;
}

function when(ms: number | null | undefined) {
  return ms ? new Date(ms).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—';
}

function Owner({ bot }: { bot: { bot_id: number; name: string } | null }) {
  return bot
    ? <span className="text-blue-300" title={`бот #${bot.bot_id}`}>{bot.name}</span>
    : <span className="text-gray-500">не бот</span>;
}

export default function AccountExchangePage() {
  const { id } = useParams<{ id: string }>();
  const accountId = Number(id);
  const [days, setDays] = useState(30);

  const { data, isLoading, isFetching, error, refetch } = useQuery<AccountExchange>({
    queryKey: ['account-exchange', accountId, days],
    queryFn: async () => (await accountsApi.exchange(accountId, days)).data,
    refetchInterval: 30_000,
  });

  const positions = data?.positions ?? [];
  const closed = data?.closed ?? [];
  const s = data?.summary;

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <Navbar />
      <div className="max-w-6xl mx-auto px-4 py-8">
        <Link href="/accounts" className="inline-flex items-center gap-1 text-sm text-gray-400 hover:text-white mb-4">
          <ArrowLeft size={14} /> Аккаунты
        </Link>
        <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
          <h1 className="text-3xl font-bold">Счёт {data?.account?.name ?? ''}</h1>
          <div className="flex items-center gap-2">
            {PERIODS.map((d) => (
              <button key={d} onClick={() => setDays(d)}
                className={`px-3 py-1 rounded text-sm ${d === days ? 'bg-blue-600' : 'bg-gray-800 hover:bg-gray-700'}`}>
                {d} дн
              </button>
            ))}
            <button onClick={() => refetch()} title="Обновить"
              className="p-2 rounded bg-gray-800 hover:bg-gray-700">
              <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>
        <p className="text-sm text-gray-400 mb-6">
          Всё, что видно на бирже через ключ «только чтение»: позиции и сделки, включая ручные и других ботов Cryptorg.
          Только просмотр — отсюда ничего не открывается и не закрывается.
        </p>

        {isLoading && <p className="text-gray-400">Загружаю с биржи…</p>}
        {error && <p className="text-red-400">{apiErrorText(error)}</p>}
        {data && !data.ok && <p className="text-red-400">{data.error}</p>}

        {data?.ok && s && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
              <Stat label="Открыто позиций" value={String(s.open_positions)} />
              <Stat label="Плавающий PnL" value={money(s.open_unrealized_pnl)} />
              <Stat label={`Закрыто за ${days} дн`} value={<>{s.closed.count} · {money(s.closed.pnl)}</>} />
              <Stat label="Боты / не боты"
                value={<span className="text-base">{s.closed.by_bots.count} {money(s.closed.by_bots.pnl)} / {s.closed.not_bots.count} {money(s.closed.not_bots.pnl)}</span>} />
            </div>

            <h2 className="text-xl font-semibold mb-3">Открытые позиции</h2>
            <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-x-auto mb-8">
              {positions.length === 0 ? <p className="p-4 text-gray-500">Открытых позиций нет</p> : (
                <table className="w-full text-sm">
                  <thead className="bg-gray-700">
                    <tr>
                      <th className="text-left py-3 px-3">Монета</th>
                      <th className="text-left py-3 px-3">Сторона</th>
                      <th className="text-right py-3 px-3">Объём, $</th>
                      <th className="text-right py-3 px-3">Средняя</th>
                      <th className="text-right py-3 px-3">Цена</th>
                      <th className="text-right py-3 px-3">PnL</th>
                      <th className="text-right py-3 px-3">Стоп / тейк на бирже</th>
                      <th className="text-right py-3 px-3">Ликвидация</th>
                      <th className="text-left py-3 px-3">Кто ведёт</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((p) => (
                      <tr key={`${p.symbol}-${p.side}`} className="border-t border-gray-700">
                        <td className="py-2 px-3 font-medium">{p.symbol}</td>
                        <td className={`py-2 px-3 ${p.side === 'LONG' ? 'text-green-400' : 'text-red-400'}`}>{p.side} ×{p.leverage}</td>
                        <td className="py-2 px-3 text-right">{p.value_usdt.toFixed(0)}</td>
                        <td className="py-2 px-3 text-right">{num(p.avg_price)}</td>
                        <td className="py-2 px-3 text-right">{num(p.mark_price)}</td>
                        <td className="py-2 px-3 text-right">{money(p.unrealized_pnl)}</td>
                        <td className="py-2 px-3 text-right text-gray-300">{num(p.stop_loss)} / {num(p.take_profit)}</td>
                        <td className="py-2 px-3 text-right text-gray-400">{num(p.liq_price)}</td>
                        <td className="py-2 px-3"><Owner bot={p.bot} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <h2 className="text-xl font-semibold mb-1">Закрытые сделки за {days} дн</h2>
            <p className="text-xs text-gray-500 mb-3">PnL — как считает Bybit (closed PnL, за вычетом комиссий).</p>
            <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-x-auto">
              {closed.length === 0 ? <p className="p-4 text-gray-500">Сделок за период нет</p> : (
                <table className="w-full text-sm">
                  <thead className="bg-gray-700">
                    <tr>
                      <th className="text-left py-3 px-3">Закрыта</th>
                      <th className="text-left py-3 px-3">Монета</th>
                      <th className="text-left py-3 px-3">Сторона</th>
                      <th className="text-right py-3 px-3">Объём, $</th>
                      <th className="text-right py-3 px-3">Вход</th>
                      <th className="text-right py-3 px-3">Выход</th>
                      <th className="text-right py-3 px-3">PnL</th>
                      <th className="text-left py-3 px-3">Кто вёл</th>
                    </tr>
                  </thead>
                  <tbody>
                    {closed.map((c, i) => (
                      <tr key={`${c.symbol}-${c.closed_at_ms}-${i}`} className="border-t border-gray-700">
                        <td className="py-2 px-3 text-gray-400">{when(c.closed_at_ms)}</td>
                        <td className="py-2 px-3 font-medium">{c.symbol}</td>
                        <td className={`py-2 px-3 ${c.side === 'LONG' ? 'text-green-400' : 'text-red-400'}`}>{c.side}</td>
                        <td className="py-2 px-3 text-right">{c.value_usdt.toFixed(0)}</td>
                        <td className="py-2 px-3 text-right">{num(c.entry_price)}</td>
                        <td className="py-2 px-3 text-right">{num(c.exit_price)}</td>
                        <td className="py-2 px-3 text-right">{money(c.pnl)}</td>
                        <td className="py-2 px-3"><Owner bot={c.bot} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="bg-gray-800 p-4 rounded-lg border border-gray-700">
      <p className="text-xs text-gray-400 mb-1">{label}</p>
      <p className="text-xl font-semibold">{value}</p>
    </div>
  );
}
