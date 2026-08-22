'use client';

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { backtestApi } from '@/lib/api';
import Navbar from '@/components/Navbar';
import { Play, Clock } from 'lucide-react';

interface BacktestStatus {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'error';
  progress: number;
  start_time: string;
  error?: string;
  results_summary?: {
    total_trades: number;
    win_rate: number | null;
    total_return: number | null;
    final_balance: number | null;
  };
}

// Бэкенд отдаёт null вместо чисел в математически неопределённых случаях
// (напр. profit_factor без единой убыточной сделки) — см. prepare_results_for_json
// в web_app.py, которая заменяет NaN/Infinity на null перед сериализацией.
type NullableNumber = number | null;

interface BacktestResults {
  basic_stats: {
    total_trades: number;
    winning_trades: number;
    losing_trades: number;
    win_rate: NullableNumber;
    total_pnl: NullableNumber;
    total_return: NullableNumber;
    current_balance: NullableNumber;
  };
  advanced_metrics: {
    max_drawdown_percent: NullableNumber;
    sharpe_ratio: NullableNumber;
    profit_factor: NullableNumber;
    avg_trade_duration_hours: NullableNumber;
    max_consecutive_wins: number;
    max_consecutive_losses: number;
  };
  trade_history: Array<{
    entry_time: string;
    exit_time: string;
    entry_price: NullableNumber;
    exit_price: NullableNumber;
    pnl: NullableNumber;
    pnl_percent: NullableNumber;
    reason?: string;
  }>;
}

function fmt(n: NullableNumber | undefined, digits = 2, suffix = ''): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return n.toFixed(digits) + suffix;
}

function fmtSigned(n: NullableNumber | undefined, digits = 2, suffix = ''): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return (n >= 0 ? '+' : '') + n.toFixed(digits) + suffix;
}

interface HistoryRow {
  task_id: string;
  symbol: string;
  timeframe: string;
  order_type: string;
  status: string;
  total_trades: number;
  win_rate: NullableNumber;
  total_return: NullableNumber;
  max_drawdown: NullableNumber;
  created_at: string;
}

function StatCard({ label, value, positive }: { label: string; value: string; positive?: boolean | null }) {
  const color = positive === undefined || positive === null ? 'text-gray-300' : positive ? 'text-green-400' : 'text-red-400';
  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <p className="text-gray-400 text-sm">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
    </div>
  );
}

function ElapsedTimer({ startTime }: { startTime: string }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const elapsedSec = Math.max(0, Math.floor((now - new Date(startTime).getTime()) / 1000));
  const mm = Math.floor(elapsedSec / 60).toString().padStart(2, '0');
  const ss = (elapsedSec % 60).toString().padStart(2, '0');

  return (
    <span className="flex items-center gap-1.5 text-yellow-300">
      <Clock size={14} /> {mm}:{ss}
    </span>
  );
}

function ResultsView({ results }: { results: BacktestResults }) {
  const { basic_stats: bs, advanced_metrics: am, trade_history } = results;
  const shownTrades = trade_history.slice(0, 200);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-4">
        <StatCard label="Total Trades" value={String(bs.total_trades)} />
        <StatCard label="Win Rate" value={fmt(bs.win_rate, 1, '%')} positive={bs.win_rate !== null ? bs.win_rate >= 50 : null} />
        <StatCard label="Total Return" value={fmtSigned(bs.total_return, 2, '%')} positive={bs.total_return !== null ? bs.total_return >= 0 : null} />
        <StatCard label="Max Drawdown" value={fmt(am.max_drawdown_percent, 2, '%')} positive={false} />
      </div>

      <div className="grid grid-cols-4 gap-4">
        <StatCard label="Sharpe Ratio" value={fmt(am.sharpe_ratio)} />
        <StatCard label="Profit Factor" value={fmt(am.profit_factor)} />
        <StatCard label="Avg Duration" value={fmt(am.avg_trade_duration_hours, 1, 'h')} />
        <StatCard label="Max Streak W/L" value={`${am.max_consecutive_wins}/${am.max_consecutive_losses}`} />
      </div>

      <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
        <div className="overflow-x-auto max-h-96 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-700 text-gray-300 uppercase text-xs sticky top-0">
              <tr>
                <th className="text-left py-2 px-3">Entry Time</th>
                <th className="text-left py-2 px-3">Exit Time</th>
                <th className="text-right py-2 px-3">Entry</th>
                <th className="text-right py-2 px-3">Exit</th>
                <th className="text-right py-2 px-3">PnL</th>
                <th className="text-right py-2 px-3">PnL %</th>
                <th className="text-left py-2 px-3">Reason</th>
              </tr>
            </thead>
            <tbody>
              {shownTrades.map((t, i) => (
                <tr key={i} className="border-t border-gray-700">
                  <td className="py-2 px-3 text-gray-400 text-xs">{t.entry_time}</td>
                  <td className="py-2 px-3 text-gray-400 text-xs">{t.exit_time}</td>
                  <td className="py-2 px-3 text-right text-gray-300">{fmt(t.entry_price)}</td>
                  <td className="py-2 px-3 text-right text-gray-300">{fmt(t.exit_price)}</td>
                  <td className={`py-2 px-3 text-right font-semibold ${(t.pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {fmtSigned(t.pnl)}
                  </td>
                  <td className={`py-2 px-3 text-right ${(t.pnl_percent ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {fmtSigned(t.pnl_percent, 2, '%')}
                  </td>
                  <td className="py-2 px-3 text-gray-400 text-xs">{t.reason ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {trade_history.length > 200 && (
          <div className="text-center py-2 text-xs text-gray-500 border-t border-gray-700">
            Показано 200 из {trade_history.length} сделок — сузьте диапазон дат для полной детализации
          </div>
        )}
      </div>
    </div>
  );
}

const EXAMPLE_CONFIGS: Record<string, string> = {
  'MRC SHORT (1 месяц)': '/mrc_reversion_15m_short-example.json',
  'MRC LONG (1 месяц)': '/mrc_reversion_15m_long-example.json',
};

export default function BacktesterPage() {
  const queryClient = useQueryClient();
  const [configText, setConfigText] = useState('');
  const [parseError, setParseError] = useState<string | null>(null);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);

  const loadExample = async (path: string) => {
    const res = await fetch(path);
    const json = await res.json();
    setConfigText(JSON.stringify(json, null, 2));
    setParseError(null);
  };

  const runMutation = useMutation({
    mutationFn: (config: object) => backtestApi.run(config),
    onSuccess: (res) => {
      setActiveTaskId(res.data.task_id);
    },
  });

  const handleRun = () => {
    try {
      const config = JSON.parse(configText);
      setParseError(null);
      runMutation.mutate(config);
    } catch (e) {
      setParseError('Некорректный JSON: ' + (e as Error).message);
    }
  };

  const { data: status, isError: statusError } = useQuery<BacktestStatus>({
    queryKey: ['backtest-status', activeTaskId],
    queryFn: async () => (await backtestApi.getStatus(activeTaskId!)).data,
    enabled: !!activeTaskId,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      if (s === 'completed' || s === 'error') return false;
      return 5000;
    },
    retry: false,
  });

  const { data: results } = useQuery<BacktestResults>({
    queryKey: ['backtest-results', activeTaskId],
    queryFn: async () => (await backtestApi.getResults(activeTaskId!)).data,
    enabled: !!activeTaskId && status?.status === 'completed',
  });

  const { data: history = [] } = useQuery<HistoryRow[]>({
    queryKey: ['backtest-history'],
    queryFn: async () => (await backtestApi.getHistory()).data,
    refetchInterval: 30000,
  });

  useEffect(() => {
    if (status?.status === 'completed') {
      queryClient.invalidateQueries({ queryKey: ['backtest-history'] });
    }
  }, [status?.status, queryClient]);

  const isRunning = status?.status === 'pending' || status?.status === 'running';

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 py-8 space-y-6">
        <div>
          <h1 className="text-3xl font-bold">Backtester</h1>
          <p className="text-gray-400 text-sm mt-1">Запуск бэктеста по конфигу стратегии, отдельная БД от торгового бэкенда</p>
        </div>

        {/* Config input */}
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 space-y-3">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm text-gray-400">Загрузить пример:</span>
            {Object.entries(EXAMPLE_CONFIGS).map(([label, path]) => (
              <button
                key={label}
                onClick={() => loadExample(path)}
                className="px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 rounded"
              >
                {label}
              </button>
            ))}
          </div>

          <textarea
            value={configText}
            onChange={(e) => { setConfigText(e.target.value); setParseError(null); }}
            placeholder="Вставьте JSON конфиг стратегии или загрузите пример выше"
            className="w-full h-64 bg-gray-900 border border-gray-700 rounded p-3 font-mono text-xs text-gray-300 focus:outline-none focus:border-blue-500"
          />

          {parseError && (
            <div className="text-red-400 text-xs bg-red-900/30 border border-red-700 rounded px-2 py-1.5">
              {parseError}
            </div>
          )}

          <div className="flex items-center gap-3">
            <button
              onClick={handleRun}
              disabled={!configText || isRunning}
              className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded text-sm font-medium"
            >
              <Play size={14} />
              {isRunning ? 'Выполняется...' : 'Запустить бэктест'}
            </button>
            <p className="text-xs text-gray-500">
              Полный год данных может занимать 20+ минут. Для быстрого теста сузьте start_date/end_date.
            </p>
          </div>
        </div>

        {/* Status */}
        {activeTaskId && (
          <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
            {statusError && (
              <p className="text-yellow-400 text-sm">
                Статус этой задачи недоступен (сервис бэктестера мог перезапуститься). Проверьте вкладку истории ниже — возможно, прогон уже завершился.
              </p>
            )}
            {!statusError && status && (
              <div className="flex items-center gap-4">
                <span className={`px-2 py-1 rounded text-xs font-medium ${
                  status.status === 'completed' ? 'bg-green-900 text-green-300' :
                  status.status === 'error' ? 'bg-red-900 text-red-300' :
                  'bg-yellow-900 text-yellow-300'
                }`}>
                  {status.status.toUpperCase()}
                </span>
                {isRunning && <ElapsedTimer startTime={status.start_time} />}
                {status.status === 'error' && (
                  <span className="text-red-400 text-sm">{status.error}</span>
                )}
              </div>
            )}
          </div>
        )}

        {/* Results */}
        {results && <ResultsView results={results} />}

        {/* History */}
        <div>
          <h2 className="text-lg font-semibold mb-3">История прогонов</h2>
          <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-700 text-gray-300 uppercase text-xs">
                <tr>
                  <th className="text-left py-2 px-3">Symbol</th>
                  <th className="text-left py-2 px-3">Side</th>
                  <th className="text-left py-2 px-3">Status</th>
                  <th className="text-right py-2 px-3">Trades</th>
                  <th className="text-right py-2 px-3">Win Rate</th>
                  <th className="text-right py-2 px-3">Return</th>
                  <th className="text-right py-2 px-3">Drawdown</th>
                  <th className="text-left py-2 px-3">Created</th>
                </tr>
              </thead>
              <tbody>
                {history.length === 0 && (
                  <tr>
                    <td colSpan={8} className="text-center py-8 text-gray-400">Прогонов пока нет</td>
                  </tr>
                )}
                {history.map((h) => (
                  <tr
                    key={h.task_id}
                    className="border-t border-gray-700 hover:bg-gray-750 cursor-pointer"
                    onClick={() => setActiveTaskId(h.task_id)}
                  >
                    <td className="py-2 px-3">{h.symbol}</td>
                    <td className="py-2 px-3">{h.order_type}</td>
                    <td className="py-2 px-3 text-gray-400 text-xs">{h.status}</td>
                    <td className="py-2 px-3 text-right">{h.total_trades}</td>
                    <td className="py-2 px-3 text-right">{fmt(h.win_rate, 1, '%')}</td>
                    <td className={`py-2 px-3 text-right ${(h.total_return ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {fmtSigned(h.total_return, 2, '%')}
                    </td>
                    <td className="py-2 px-3 text-right text-red-400">{fmt(h.max_drawdown, 2, '%')}</td>
                    <td className="py-2 px-3 text-gray-400 text-xs">
                      {new Date(h.created_at).toLocaleString('ru', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
