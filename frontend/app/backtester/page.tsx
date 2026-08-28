'use client';

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { backtestApi } from '@/lib/api';
import Navbar from '@/components/Navbar';
import { Play, Clock, ChevronDown, ChevronUp, Code2, Download } from 'lucide-react';

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
    total_orders?: number;
    dca_orders_count?: number;
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

  // Бэкенд отдаёт naive datetime.isoformat() без указания зоны (сервер в UTC) —
  // без суффикса JS парсит строку как локальное время браузера, что даёт
  // огромный ложный elapsed сразу после старта в любой зоне восточнее UTC.
  const startMs = new Date(/[Z+-]\d{2}:?\d{2}$|Z$/.test(startTime) ? startTime : startTime + 'Z').getTime();
  const elapsedSec = Math.max(0, Math.floor((now - startMs) / 1000));
  const mm = Math.floor(elapsedSec / 60).toString().padStart(2, '0');
  const ss = (elapsedSec % 60).toString().padStart(2, '0');

  return (
    <span className="flex items-center gap-1.5 text-yellow-300">
      <Clock size={14} /> {mm}:{ss}
    </span>
  );
}

function tradesToCsv(trades: BacktestResults['trade_history']): string {
  const headers = ['entry_time', 'exit_time', 'entry_price', 'exit_price', 'total_orders', 'dca_orders_count', 'pnl', 'pnl_percent', 'reason'];
  const rows = trades.map(t => [
    t.entry_time,
    t.exit_time,
    t.entry_price ?? '',
    t.exit_price ?? '',
    t.total_orders ?? '',
    t.dca_orders_count ?? '',
    t.pnl ?? '',
    t.pnl_percent ?? '',
    t.reason ?? '',
  ]);
  return [headers, ...rows]
    .map(row => row.map(cell => {
      const s = String(cell);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(','))
    .join('\n');
}

function downloadCsv(filename: string, csv: string) {
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function ResultsView({ results, taskId }: { results: BacktestResults; taskId: string }) {
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
        <div className="flex items-center justify-between px-3 py-2 border-b border-gray-700">
          <span className="text-xs text-gray-400">Список сделок ({trade_history.length})</span>
          <button
            onClick={() => downloadCsv(`trades_${taskId.slice(0, 8)}.csv`, tradesToCsv(trade_history))}
            disabled={trade_history.length === 0}
            className="flex items-center gap-1.5 px-2.5 py-1 text-xs bg-gray-700 hover:bg-gray-600 disabled:opacity-50 rounded"
          >
            <Download size={13} /> Скачать CSV
          </button>
        </div>
        <div className="overflow-x-auto max-h-96 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-700 text-gray-300 uppercase text-xs sticky top-0">
              <tr>
                <th className="text-left py-2 px-3">Entry Time</th>
                <th className="text-left py-2 px-3">Exit Time</th>
                <th className="text-right py-2 px-3">Entry</th>
                <th className="text-right py-2 px-3">Exit</th>
                <th className="text-right py-2 px-3">Orders</th>
                <th className="text-right py-2 px-3">PnL</th>
                <th className="text-right py-2 px-3">PnL %</th>
                <th className="text-left py-2 px-3">Reason</th>
              </tr>
            </thead>
            <tbody>
              {shownTrades.map((t, i) => {
                const isOpenAtEnd = t.reason === 'end_of_data';
                const pnlColor = isOpenAtEnd ? 'text-gray-400' : (t.pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400';
                return (
                  <tr key={i} className={`border-t border-gray-700 ${isOpenAtEnd ? 'opacity-60' : ''}`}>
                    <td className="py-2 px-3 text-gray-400 text-xs">{t.entry_time}</td>
                    <td className="py-2 px-3 text-gray-400 text-xs">{t.exit_time}</td>
                    <td className="py-2 px-3 text-right text-gray-300">{fmt(t.entry_price)}</td>
                    <td className="py-2 px-3 text-right text-gray-300">{fmt(t.exit_price)}</td>
                    <td className="py-2 px-3 text-right text-gray-300">
                      {t.total_orders ?? '—'}
                      {!!t.dca_orders_count && <span className="text-gray-500"> ({t.dca_orders_count} DCA)</span>}
                    </td>
                    <td className={`py-2 px-3 text-right font-semibold ${pnlColor}`}>
                      {fmtSigned(t.pnl)}
                    </td>
                    <td className={`py-2 px-3 text-right ${pnlColor}`}>
                      {fmtSigned(t.pnl_percent, 2, '%')}
                    </td>
                    <td className="py-2 px-3 text-xs">
                      {isOpenAtEnd ? (
                        <span className="text-yellow-400" title="Позиция была ещё открыта на момент окончания исторических данных — это не реальный убыточный выход, а незавершённая сделка, вынужденно закрытая по последней цене для подсчёта незавершённой позиции. Исключена из общей статистики (win rate, total return и т.д.)">
                          Открыта на конец периода
                        </span>
                      ) : (t.reason ?? '—')}
                    </td>
                  </tr>
                );
              })}
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

// ---------------------------------------------------------------------------
// Секционная форма конфига — заменяет сырой JSON textarea. Каждая секция
// свёрнута в объект state и на кнопке "Запустить" собирается в тот же JSON,
// что раньше писался руками (структура зафиксирована backtester'ом,
// см. services/backtester/strategy.py / indicators.py).
// ---------------------------------------------------------------------------

type IndicatorStrategy = 'none' | 'trend_momentum' | 'volatility_bounce' | 'momentum_trend' | 'mrc_reversion' | 'mrc_trend_filtered' | 'custom';

const INDICATOR_LABELS: Record<IndicatorStrategy, string> = {
  none: 'Без индикатора (только DCA-сетка)',
  trend_momentum: 'Trend + Momentum (EMA + RSI)',
  volatility_bounce: 'Volatility Bounce (Bollinger + ATR)',
  momentum_trend: 'Momentum + Trend (SuperTrend + Stoch RSI)',
  mrc_reversion: 'MRC Reversion (Mean Reversion Channel)',
  mrc_trend_filtered: 'MRC + тренд-фильтр (4H EMA + 1H/15m MRC)',
  custom: 'Свой набор — выбрать индикаторы вручную',
};

type CustomIndicatorKey = 'ema' | 'rsi' | 'bollinger_bands' | 'atr' | 'supertrend' | 'stochastic_rsi' | 'adx';

interface FormState {
  symbol: string;
  exchange: string;
  order_type: 'long' | 'short';
  timeframe: string;
  start_date: string;
  end_date: string;
  start_balance: number;
  leverage: number;
  commission_rate: number;
  entry_mode: 'percent' | 'fixed';
  entry_percent: number;
  entry_fixed_usdt: number;
  dca_enabled: boolean;
  dca_max_orders: number;
  dca_step_percent: number;
  martingale_enabled: boolean;
  martingale_multiplier: number;
  pyramid_enabled: boolean;
  pyramid_max_orders: number;
  pyramid_step_percent: number;
  pyramid_size_progression: 'decreasing' | 'fixed';
  pyramid_size_multiplier: number;
  tp_enabled: boolean;
  tp_percent: number;
  sl_enabled: boolean;
  sl_percent: number;
  max_drawdown_percent: number;
  indicator: IndicatorStrategy;
  // trend_momentum
  ema_short: number;
  ema_long: number;
  rsi_period: number;
  rsi_oversold: number;
  rsi_overbought: number;
  // volatility_bounce
  bb_period: number;
  bb_std: number;
  atr_period: number;
  // momentum_trend
  supertrend_period: number;
  supertrend_multiplier: number;
  stoch_rsi_k: number;
  stoch_rsi_d: number;
  stoch_oversold_level: number;
  stoch_overbought_level: number;
  // mrc_reversion
  mrc_length: number;
  mrc_inner_mult: number;
  mrc_outer_mult: number;
  mrc_gradsize: number;
  mrc_entry_band: number;
  mrc_source: 'hlc3' | 'close' | 'ohlc4';
  // mrc_trend_filtered — MRC вход (mrc_length/inner/outer/gradsize/source общие
  // с mrc_reversion) + тренд-фильтр на отдельном, более старшем таймфрейме
  trend_timeframe: string;
  mtf_entry_band: '1' | '2' | '1_2';
  mtf_trend_ema_period: number;
  // custom — свой набор индикаторов
  custom_selected: Record<CustomIndicatorKey, boolean>;
  custom_ema_mode: 'cross' | 'price_vs_ema';
  custom_ema_short: number;
  custom_ema_long: number;
  custom_ema_price_period: number;
  custom_rsi_period: number;
  custom_rsi_mode: 'level' | 'crossover';
  custom_rsi_oversold: number;
  custom_rsi_overbought: number;
  custom_rsi_cross_long: number;
  custom_rsi_cross_short: number;
  custom_bb_period: number;
  custom_bb_std: number;
  custom_atr_period: number;
  custom_supertrend_period: number;
  custom_supertrend_multiplier: number;
  custom_stoch_k: number;
  custom_stoch_d: number;
  custom_stoch_rsi_period: number;
  custom_stoch_oversold: number;
  custom_stoch_overbought: number;
  custom_adx_period: number;
  custom_adx_max: number;
}

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function defaultDateRange(monthsBack = 3): { start_date: string; end_date: string } {
  const end = new Date();
  const start = new Date(end);
  start.setMonth(start.getMonth() - monthsBack);
  return { start_date: isoDate(start), end_date: isoDate(end) };
}

const DEFAULT_FORM: FormState = {
  symbol: 'BTC/USDT',
  exchange: 'binance',
  order_type: 'long',
  timeframe: '15m',
  ...defaultDateRange(3),
  start_balance: 10000,
  leverage: 10,
  commission_rate: 0.04,
  entry_mode: 'percent',
  entry_percent: 10,
  entry_fixed_usdt: 100,
  dca_enabled: true,
  dca_max_orders: 3,
  dca_step_percent: 1.55,
  martingale_enabled: true,
  martingale_multiplier: 2.0,
  pyramid_enabled: false,
  pyramid_max_orders: 3,
  pyramid_step_percent: 1.5,
  pyramid_size_progression: 'decreasing',
  pyramid_size_multiplier: 0.5,
  tp_enabled: true,
  tp_percent: 0.97,
  sl_enabled: false,
  sl_percent: 5,
  max_drawdown_percent: 20,
  indicator: 'mrc_reversion',
  ema_short: 50,
  ema_long: 200,
  rsi_period: 14,
  rsi_oversold: 30,
  rsi_overbought: 70,
  bb_period: 20,
  bb_std: 2,
  atr_period: 14,
  supertrend_period: 10,
  supertrend_multiplier: 3,
  stoch_rsi_k: 14,
  stoch_rsi_d: 3,
  stoch_oversold_level: 20,
  stoch_overbought_level: 80,
  mrc_length: 200,
  mrc_inner_mult: 1.0,
  mrc_outer_mult: 2.415,
  mrc_gradsize: 0.5,
  mrc_entry_band: 2,
  trend_timeframe: '4h',
  mtf_entry_band: '1_2',
  mtf_trend_ema_period: 21,
  mrc_source: 'hlc3',
  custom_selected: { ema: true, rsi: true, bollinger_bands: false, atr: false, supertrend: false, stochastic_rsi: false, adx: false },
  custom_ema_mode: 'cross',
  custom_ema_short: 50,
  custom_ema_long: 200,
  custom_ema_price_period: 200,
  custom_rsi_period: 14,
  custom_rsi_mode: 'level',
  custom_rsi_oversold: 30,
  custom_rsi_overbought: 70,
  custom_rsi_cross_long: 38,
  custom_rsi_cross_short: 62,
  custom_bb_period: 20,
  custom_bb_std: 2,
  custom_atr_period: 14,
  custom_supertrend_period: 10,
  custom_supertrend_multiplier: 3,
  custom_stoch_k: 14,
  custom_stoch_d: 3,
  custom_stoch_rsi_period: 14,
  custom_stoch_oversold: 20,
  custom_stoch_overbought: 80,
  custom_adx_period: 14,
  custom_adx_max: 25,
};

function buildConfig(f: FormState): object {
  const config: any = {
    start_balance: f.start_balance,
    leverage: f.leverage,
    order_type: f.order_type,
    timeframe: f.timeframe,
    commission_rate: f.commission_rate / 100,
    start_date: f.start_date,
    end_date: f.end_date,
    first_order: f.entry_mode === 'fixed'
      ? { type: 'fixed', amount_fixed: f.entry_fixed_usdt }
      : { type: 'percent', amount_percent: f.entry_percent },
    dca: {
      enabled: f.dca_enabled,
      max_orders: f.dca_max_orders,
      step_price: { type: 'fixed_percent', value: f.dca_step_percent },
      martingale: { enabled: f.martingale_enabled, multiplier: f.martingale_multiplier },
    },
    pyramid: {
      enabled: f.pyramid_enabled,
      max_orders: f.pyramid_max_orders,
      trigger: { type: 'fixed_percent', value: f.pyramid_step_percent },
      size_progression: f.pyramid_size_progression,
      size_multiplier: f.pyramid_size_multiplier,
      stop_advance: 'to_prev_entry',
    },
    take_profit: {
      enabled: f.tp_enabled,
      percent: f.tp_percent,
      trailing: { enabled: false },
    },
    stop_loss: { enabled: f.sl_enabled, percent: f.sl_percent },
    risk_management: { max_drawdown_percent: f.max_drawdown_percent, max_open_positions: 1 },
    data_source: {
      type: 'api',
      api: { exchange: f.exchange, symbol: f.symbol, market_type: 'futures' },
    },
  };

  if (f.indicator === 'none') {
    config.indicators = { enabled: false };
  } else if (f.indicator === 'trend_momentum') {
    config.indicators = {
      enabled: true,
      strategy_type: 'trend_momentum',
      trend_momentum: {
        ema_short: f.ema_short,
        ema_long: f.ema_long,
        rsi_period: f.rsi_period,
        rsi_oversold: f.rsi_oversold,
        rsi_overbought: f.rsi_overbought,
      },
    };
  } else if (f.indicator === 'volatility_bounce') {
    config.indicators = {
      enabled: true,
      strategy_type: 'volatility_bounce',
      volatility_bounce: { bb_period: f.bb_period, bb_std: f.bb_std, atr_period: f.atr_period },
    };
  } else if (f.indicator === 'momentum_trend') {
    config.indicators = {
      enabled: true,
      strategy_type: 'momentum_trend',
      momentum_trend: {
        supertrend_period: f.supertrend_period,
        supertrend_multiplier: f.supertrend_multiplier,
        stoch_rsi_k: f.stoch_rsi_k,
        stoch_rsi_d: f.stoch_rsi_d,
        stoch_oversold_level: f.stoch_oversold_level,
        stoch_overbought_level: f.stoch_overbought_level,
      },
    };
  } else if (f.indicator === 'mrc_reversion') {
    config.indicators = {
      enabled: true,
      strategy_type: 'mrc_reversion',
      mrc_reversion: {
        length: f.mrc_length,
        inner_mult: f.mrc_inner_mult,
        outer_mult: f.mrc_outer_mult,
        gradsize: f.mrc_gradsize,
        entry_band: f.mrc_entry_band,
        source: f.mrc_source,
      },
    };
  } else if (f.indicator === 'mrc_trend_filtered') {
    // Третий, независимый таймфрейм (реальные биржевые свечи, не ресемплинг —
    // см. backtester.py/data_loader.py) для тренд-фильтра поверх MRC-входа.
    config.trend_timeframe = f.trend_timeframe;
    config.indicators = {
      enabled: true,
      strategy_type: 'mrc_trend_filtered',
      mrc_trend_filtered: {
        length: f.mrc_length,
        inner_mult: f.mrc_inner_mult,
        outer_mult: f.mrc_outer_mult,
        gradsize: f.mrc_gradsize,
        entry_band: f.mtf_entry_band === '1_2' ? [1, 2] : parseInt(f.mtf_entry_band, 10),
        source: f.mrc_source,
        trend_ema_period: f.mtf_trend_ema_period,
      },
    };
  } else if (f.indicator === 'custom') {
    const indicators: any = { enabled: true, selected_indicators: f.custom_selected };

    if (f.custom_selected.ema) {
      indicators.ema = f.custom_ema_mode === 'price_vs_ema'
        ? { use_price_comparison: true, period: f.custom_ema_price_period }
        : { use_price_comparison: false, short_period: f.custom_ema_short, long_period: f.custom_ema_long };
    }
    if (f.custom_selected.rsi) {
      indicators.rsi = f.custom_rsi_mode === 'crossover'
        ? { period: f.custom_rsi_period, use_crossover: true, crossover_level_long: f.custom_rsi_cross_long, crossover_level_short: f.custom_rsi_cross_short }
        : { period: f.custom_rsi_period, use_crossover: false, oversold: f.custom_rsi_oversold, overbought: f.custom_rsi_overbought };
    }
    if (f.custom_selected.bollinger_bands) {
      indicators.bollinger_bands = { period: f.custom_bb_period, std_dev: f.custom_bb_std };
    }
    if (f.custom_selected.atr) {
      indicators.atr = { period: f.custom_atr_period };
    }
    if (f.custom_selected.supertrend) {
      indicators.supertrend = { period: f.custom_supertrend_period, multiplier: f.custom_supertrend_multiplier };
    }
    if (f.custom_selected.stochastic_rsi) {
      indicators.stochastic_rsi = {
        k_period: f.custom_stoch_k, d_period: f.custom_stoch_d, rsi_period: f.custom_stoch_rsi_period,
        oversold_level: f.custom_stoch_oversold, overbought_level: f.custom_stoch_overbought,
      };
    }
    if (f.custom_selected.adx) {
      indicators.adx = { period: f.custom_adx_period, max_value: f.custom_adx_max };
    }

    config.indicators = indicators;
  }

  return config;
}

function Section({ title, defaultOpen = true, children }: { title: string; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-gray-700 rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-750 hover:bg-gray-700 text-sm font-medium text-gray-200"
      >
        {title}
        {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>
      {open && <div className="p-4 space-y-3 bg-gray-800">{children}</div>}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-gray-400">
      {label}
      {children}
    </label>
  );
}

const inputCls = "bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-blue-500";

function NumberField({ label, value, onChange, step }: { label: string; value: number; onChange: (v: number) => void; step?: number }) {
  return (
    <Field label={label}>
      <input
        type="number"
        step={step ?? 'any'}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className={inputCls}
      />
    </Field>
  );
}

function IndicatorFields({ form, setForm }: { form: FormState; setForm: (updater: (f: FormState) => FormState) => void }) {
  const set = <K extends keyof FormState>(key: K) => (v: FormState[K]) => setForm(f => ({ ...f, [key]: v }));

  if (form.indicator === 'none') {
    return <p className="text-xs text-gray-500">Вход происходит только по правилам DCA-сетки, без индикаторного фильтра.</p>;
  }

  if (form.indicator === 'trend_momentum') {
    return (
      <div className="grid grid-cols-3 gap-3">
        <NumberField label="EMA короткая" value={form.ema_short} onChange={set('ema_short')} />
        <NumberField label="EMA длинная" value={form.ema_long} onChange={set('ema_long')} />
        <NumberField label="RSI период" value={form.rsi_period} onChange={set('rsi_period')} />
        <NumberField label="RSI oversold" value={form.rsi_oversold} onChange={set('rsi_oversold')} />
        <NumberField label="RSI overbought" value={form.rsi_overbought} onChange={set('rsi_overbought')} />
      </div>
    );
  }

  if (form.indicator === 'volatility_bounce') {
    return (
      <div className="grid grid-cols-3 gap-3">
        <NumberField label="Bollinger период" value={form.bb_period} onChange={set('bb_period')} />
        <NumberField label="Bollinger std" value={form.bb_std} onChange={set('bb_std')} step={0.1} />
        <NumberField label="ATR период" value={form.atr_period} onChange={set('atr_period')} />
      </div>
    );
  }

  if (form.indicator === 'momentum_trend') {
    return (
      <div className="grid grid-cols-3 gap-3">
        <NumberField label="SuperTrend период" value={form.supertrend_period} onChange={set('supertrend_period')} />
        <NumberField label="SuperTrend множитель" value={form.supertrend_multiplier} onChange={set('supertrend_multiplier')} step={0.1} />
        <NumberField label="Stoch RSI K" value={form.stoch_rsi_k} onChange={set('stoch_rsi_k')} />
        <NumberField label="Stoch RSI D" value={form.stoch_rsi_d} onChange={set('stoch_rsi_d')} />
        <NumberField label="Stoch oversold" value={form.stoch_oversold_level} onChange={set('stoch_oversold_level')} />
        <NumberField label="Stoch overbought" value={form.stoch_overbought_level} onChange={set('stoch_overbought_level')} />
      </div>
    );
  }

  if (form.indicator === 'mrc_reversion') {
    return (
      <div className="grid grid-cols-3 gap-3">
        <NumberField label="Length" value={form.mrc_length} onChange={set('mrc_length')} />
        <NumberField label="Inner mult" value={form.mrc_inner_mult} onChange={set('mrc_inner_mult')} step={0.01} />
        <NumberField label="Outer mult" value={form.mrc_outer_mult} onChange={set('mrc_outer_mult')} step={0.001} />
        <NumberField label="Gradsize" value={form.mrc_gradsize} onChange={set('mrc_gradsize')} step={0.01} />
        <Field label="Entry band">
          <select
            value={form.mrc_entry_band}
            onChange={(e) => set('mrc_entry_band')(parseInt(e.target.value))}
            className={inputCls}
          >
            <option value={1}>1 — лёгкий выход за внешнюю полосу (ранний, самый частый сигнал)</option>
            <option value={2}>2 — цена дошла до внешней полосы (дефолт live-бота)</option>
            <option value={3}>3 — экстремальное отклонение (самый глубокий, самый редкий сигнал)</option>
          </select>
        </Field>
        <Field label="Source">
          <select
            value={form.mrc_source}
            onChange={(e) => set('mrc_source')(e.target.value as FormState['mrc_source'])}
            className={inputCls}
          >
            <option value="hlc3">hlc3</option>
            <option value="close">close</option>
            <option value="ohlc4">ohlc4</option>
          </select>
        </Field>
      </div>
    );
  }

  if (form.indicator === 'mrc_trend_filtered') {
    return (
      <div className="space-y-3">
        <p className="text-xs text-gray-500">
          Вход только когда тренд на старшем ТФ совпадает с направлением: цена выше EMA (4H) + MRC на
          основном ТФ ({form.timeframe}) коснулся выбранной полосы. Тренд-ТФ грузится реальными биржевыми
          свечами (не ресемплинг), как в live-боте.
        </p>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Тренд-таймфрейм">
            <select value={form.trend_timeframe} onChange={e => setForm(f => ({ ...f, trend_timeframe: e.target.value }))} className={inputCls}>
              <option value="1h">1h</option>
              <option value="4h">4h</option>
              <option value="1d">1d</option>
            </select>
          </Field>
          <NumberField label="Тренд EMA период" value={form.mtf_trend_ema_period} onChange={set('mtf_trend_ema_period')} />
          <Field label="MRC entry band">
            <select
              value={form.mtf_entry_band}
              onChange={(e) => set('mtf_entry_band')(e.target.value as FormState['mtf_entry_band'])}
              className={inputCls}
            >
              <option value="1">1 — лёгкий выход за внешнюю полосу</option>
              <option value="2">2 — цена дошла до внешней полосы</option>
              <option value="1_2">1 или 2 — любая из двух (шире вход)</option>
            </select>
          </Field>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <NumberField label="MRC Length" value={form.mrc_length} onChange={set('mrc_length')} />
          <NumberField label="Inner mult" value={form.mrc_inner_mult} onChange={set('mrc_inner_mult')} step={0.01} />
          <NumberField label="Outer mult" value={form.mrc_outer_mult} onChange={set('mrc_outer_mult')} step={0.001} />
          <NumberField label="Gradsize" value={form.mrc_gradsize} onChange={set('mrc_gradsize')} step={0.01} />
          <Field label="Source">
            <select
              value={form.mrc_source}
              onChange={(e) => set('mrc_source')(e.target.value as FormState['mrc_source'])}
              className={inputCls}
            >
              <option value="hlc3">hlc3</option>
              <option value="close">close</option>
              <option value="ohlc4">ohlc4</option>
            </select>
          </Field>
        </div>
      </div>
    );
  }

  // custom — свой набор индикаторов, комбинируются через AND (все выбранные
  // должны согласованно дать сигнал long/short одновременно)
  const toggleIndicator = (key: CustomIndicatorKey) => (checked: boolean) =>
    setForm(f => ({ ...f, custom_selected: { ...f.custom_selected, [key]: checked } }));

  const noneSelected = !Object.values(form.custom_selected).some(Boolean);

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">Все включённые индикаторы должны одновременно согласиться на long/short (условие AND).</p>
      {noneSelected && (
        <p className="text-xs text-yellow-400">Выберите хотя бы один индикатор — иначе сигналов не будет вообще.</p>
      )}

      <IndicatorCheckbox label="EMA — трендовый фильтр" checked={form.custom_selected.ema} onChange={toggleIndicator('ema')}>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Режим">
            <select value={form.custom_ema_mode} onChange={e => setForm(f => ({ ...f, custom_ema_mode: e.target.value as FormState['custom_ema_mode'] }))} className={inputCls}>
              <option value="cross">EMA short vs EMA long</option>
              <option value="price_vs_ema">Цена vs одна EMA</option>
            </select>
          </Field>
          {form.custom_ema_mode === 'cross' ? (
            <>
              <NumberField label="EMA short" value={form.custom_ema_short} onChange={set('custom_ema_short')} />
              <NumberField label="EMA long" value={form.custom_ema_long} onChange={set('custom_ema_long')} />
            </>
          ) : (
            <NumberField label="EMA период" value={form.custom_ema_price_period} onChange={set('custom_ema_price_period')} />
          )}
        </div>
      </IndicatorCheckbox>

      <IndicatorCheckbox label="RSI — моментум" checked={form.custom_selected.rsi} onChange={toggleIndicator('rsi')}>
        <div className="grid grid-cols-3 gap-3">
          <NumberField label="Период" value={form.custom_rsi_period} onChange={set('custom_rsi_period')} />
          <Field label="Режим">
            <select value={form.custom_rsi_mode} onChange={e => setForm(f => ({ ...f, custom_rsi_mode: e.target.value as FormState['custom_rsi_mode'] }))} className={inputCls}>
              <option value="level">Уровень oversold/overbought</option>
              <option value="crossover">Пересечение уровня</option>
            </select>
          </Field>
          {form.custom_rsi_mode === 'level' ? (
            <>
              <NumberField label="Oversold" value={form.custom_rsi_oversold} onChange={set('custom_rsi_oversold')} />
              <NumberField label="Overbought" value={form.custom_rsi_overbought} onChange={set('custom_rsi_overbought')} />
            </>
          ) : (
            <>
              <NumberField label="Уровень для long" value={form.custom_rsi_cross_long} onChange={set('custom_rsi_cross_long')} />
              <NumberField label="Уровень для short" value={form.custom_rsi_cross_short} onChange={set('custom_rsi_cross_short')} />
            </>
          )}
        </div>
      </IndicatorCheckbox>

      <IndicatorCheckbox label="Bollinger Bands — волатильность" checked={form.custom_selected.bollinger_bands} onChange={toggleIndicator('bollinger_bands')}>
        <div className="grid grid-cols-3 gap-3">
          <NumberField label="Период" value={form.custom_bb_period} onChange={set('custom_bb_period')} />
          <NumberField label="Std dev" value={form.custom_bb_std} onChange={set('custom_bb_std')} step={0.1} />
        </div>
      </IndicatorCheckbox>

      <IndicatorCheckbox label="ATR — фильтр низкой волатильности" checked={form.custom_selected.atr} onChange={toggleIndicator('atr')}>
        <div className="grid grid-cols-3 gap-3">
          <NumberField label="Период" value={form.custom_atr_period} onChange={set('custom_atr_period')} />
        </div>
      </IndicatorCheckbox>

      <IndicatorCheckbox label="SuperTrend — направление тренда" checked={form.custom_selected.supertrend} onChange={toggleIndicator('supertrend')}>
        <div className="grid grid-cols-3 gap-3">
          <NumberField label="Период" value={form.custom_supertrend_period} onChange={set('custom_supertrend_period')} />
          <NumberField label="Множитель" value={form.custom_supertrend_multiplier} onChange={set('custom_supertrend_multiplier')} step={0.1} />
        </div>
      </IndicatorCheckbox>

      <IndicatorCheckbox label="Stochastic RSI — моментум" checked={form.custom_selected.stochastic_rsi} onChange={toggleIndicator('stochastic_rsi')}>
        <div className="grid grid-cols-3 gap-3">
          <NumberField label="K период" value={form.custom_stoch_k} onChange={set('custom_stoch_k')} />
          <NumberField label="D период" value={form.custom_stoch_d} onChange={set('custom_stoch_d')} />
          <NumberField label="RSI период" value={form.custom_stoch_rsi_period} onChange={set('custom_stoch_rsi_period')} />
          <NumberField label="Oversold" value={form.custom_stoch_oversold} onChange={set('custom_stoch_oversold')} />
          <NumberField label="Overbought" value={form.custom_stoch_overbought} onChange={set('custom_stoch_overbought')} />
        </div>
      </IndicatorCheckbox>

      <IndicatorCheckbox label="ADX — фильтр силы тренда" checked={form.custom_selected.adx} onChange={toggleIndicator('adx')}>
        <div className="grid grid-cols-3 gap-3">
          <NumberField label="Период" value={form.custom_adx_period} onChange={set('custom_adx_period')} />
          <NumberField label="Макс. значение (флэт)" value={form.custom_adx_max} onChange={set('custom_adx_max')} />
        </div>
      </IndicatorCheckbox>
    </div>
  );
}

function IndicatorCheckbox({ label, checked, onChange, children }: { label: string; checked: boolean; onChange: (v: boolean) => void; children: React.ReactNode }) {
  return (
    <div className="border border-gray-700 rounded-lg p-3">
      <label className="flex items-center gap-2 text-sm text-gray-200 cursor-pointer">
        <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} className="accent-blue-500" />
        {label}
      </label>
      {checked && <div className="mt-2">{children}</div>}
    </div>
  );
}

const EXAMPLE_CONFIGS: Record<string, string> = {
  'MRC SHORT (1 месяц)': '/mrc_reversion_15m_short-example.json',
  'MRC LONG (1 месяц)': '/mrc_reversion_15m_long-example.json',
};

export default function BacktesterPage() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [advancedMode, setAdvancedMode] = useState(false);
  const [configText, setConfigText] = useState(() => JSON.stringify(buildConfig(DEFAULT_FORM), null, 2));
  const [parseError, setParseError] = useState<string | null>(null);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);

  const loadExample = async (path: string) => {
    const res = await fetch(path);
    const json = await res.json();
    setConfigText(JSON.stringify(json, null, 2));
    setAdvancedMode(true);
    setParseError(null);
  };

  const runMutation = useMutation({
    mutationFn: (config: object) => backtestApi.run(config),
    onSuccess: (res) => {
      setActiveTaskId(res.data.task_id);
    },
  });

  const handleRun = () => {
    const config = advancedMode ? safeParseJson(configText) : buildConfig(form);
    if (config === null) {
      setParseError('Некорректный JSON');
      return;
    }
    setParseError(null);
    runMutation.mutate(config);
  };

  const safeParseJson = (text: string): object | null => {
    try {
      return JSON.parse(text);
    } catch (e) {
      setParseError('Некорректный JSON: ' + (e as Error).message);
      return null;
    }
  };

  const switchToAdvanced = () => {
    setConfigText(JSON.stringify(buildConfig(form), null, 2));
    setAdvancedMode(true);
  };

  const { data: status, isError: statusError } = useQuery<BacktestStatus>({
    queryKey: ['backtest-status', activeTaskId],
    queryFn: async () => (await backtestApi.getStatus(activeTaskId!)).data,
    enabled: !!activeTaskId,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      if (s === 'completed' || s === 'error') return false;
      return 2000;
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
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Backtester</h1>
            <p className="text-gray-400 text-sm mt-1">Бэктест стратегии на исторических данных, отдельная БД от торгового бэкенда</p>
          </div>
          <button
            onClick={() => advancedMode ? setAdvancedMode(false) : switchToAdvanced()}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded"
          >
            <Code2 size={14} />
            {advancedMode ? 'Вернуться к форме' : 'Редактировать как JSON'}
          </button>
        </div>

        {/* Config input */}
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 space-y-4">
          {advancedMode ? (
            <>
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
                placeholder="JSON конфиг стратегии"
                className="w-full h-80 bg-gray-900 border border-gray-700 rounded p-3 font-mono text-xs text-gray-300 focus:outline-none focus:border-blue-500"
              />
            </>
          ) : (
            <>
              <Section title="Рынок и период">
                <div className="grid grid-cols-4 gap-3">
                  <Field label="Символ">
                    <input value={form.symbol} onChange={e => setForm(f => ({ ...f, symbol: e.target.value }))} className={inputCls} />
                  </Field>
                  <Field label="Биржа">
                    <select value={form.exchange} onChange={e => setForm(f => ({ ...f, exchange: e.target.value }))} className={inputCls}>
                      <option value="binance">binance</option>
                      <option value="bybit">bybit</option>
                      <option value="okx">okx</option>
                    </select>
                  </Field>
                  <Field label="Направление">
                    <select value={form.order_type} onChange={e => setForm(f => ({ ...f, order_type: e.target.value as 'long' | 'short' }))} className={inputCls}>
                      <option value="long">Long</option>
                      <option value="short">Short</option>
                    </select>
                  </Field>
                  <Field label="Таймфрейм">
                    <select value={form.timeframe} onChange={e => setForm(f => ({ ...f, timeframe: e.target.value }))} className={inputCls}>
                      <option value="5m">5m</option>
                      <option value="15m">15m</option>
                      <option value="1h">1h</option>
                      <option value="4h">4h</option>
                    </select>
                  </Field>
                  <Field label="С даты">
                    <input type="date" value={form.start_date} onChange={e => setForm(f => ({ ...f, start_date: e.target.value }))} className={inputCls} />
                  </Field>
                  <Field label="По дату">
                    <input type="date" value={form.end_date} onChange={e => setForm(f => ({ ...f, end_date: e.target.value }))} className={inputCls} />
                  </Field>
                  <NumberField label="Депозит ($)" value={form.start_balance} onChange={v => setForm(f => ({ ...f, start_balance: v }))} />
                  <NumberField label="Плечо" value={form.leverage} onChange={v => setForm(f => ({ ...f, leverage: v }))} />
                  <NumberField label="Комиссия (%)" value={form.commission_rate} onChange={v => setForm(f => ({ ...f, commission_rate: v }))} step={0.01} />
                </div>
              </Section>

              <Section title="Вход и DCA-сетка">
                <div className="grid grid-cols-4 gap-3">
                  <Field label="Первый ордер, тип">
                    <select
                      value={form.entry_mode}
                      onChange={e => setForm(f => ({ ...f, entry_mode: e.target.value as FormState['entry_mode'] }))}
                      className={inputCls}
                    >
                      <option value="percent">% от депозита</option>
                      <option value="fixed">Фиксированная сумма (USDT)</option>
                    </select>
                  </Field>
                  {form.entry_mode === 'fixed' ? (
                    <NumberField label="Первый ордер (USDT)" value={form.entry_fixed_usdt} onChange={v => setForm(f => ({ ...f, entry_fixed_usdt: v }))} />
                  ) : (
                    <NumberField label="Первый ордер (% депозита)" value={form.entry_percent} onChange={v => setForm(f => ({ ...f, entry_percent: v }))} />
                  )}
                  <Field label="DCA доборы">
                    <select value={form.dca_enabled ? '1' : '0'} onChange={e => setForm(f => ({ ...f, dca_enabled: e.target.value === '1' }))} className={inputCls}>
                      <option value="1">Включены</option>
                      <option value="0">Выключены</option>
                    </select>
                  </Field>
                  {form.dca_enabled && (
                    <>
                      <NumberField label="Максимум ордеров" value={form.dca_max_orders} onChange={v => setForm(f => ({ ...f, dca_max_orders: v }))} />
                      <NumberField label="Шаг добора (%)" value={form.dca_step_percent} onChange={v => setForm(f => ({ ...f, dca_step_percent: v }))} step={0.01} />
                      <Field label="Martingale">
                        <select value={form.martingale_enabled ? '1' : '0'} onChange={e => setForm(f => ({ ...f, martingale_enabled: e.target.value === '1' }))} className={inputCls}>
                          <option value="1">Включён</option>
                          <option value="0">Выключен</option>
                        </select>
                      </Field>
                      {form.martingale_enabled && (
                        <NumberField label="Множитель" value={form.martingale_multiplier} onChange={v => setForm(f => ({ ...f, martingale_multiplier: v }))} step={0.1} />
                      )}
                    </>
                  )}
                </div>
              </Section>

              <Section title="Пирамидинг" defaultOpen={false}>
                <p className="text-xs text-gray-500">
                  В отличие от DCA (усреднение в убытке), пирамидинг докупает ПО тренду — когда цена уже
                  пошла в прибыль от последнего входа. Размер каждой докупки по умолчанию убывающий, а Stop
                  Loss подтягивается к цене предыдущего входа при каждом добавлении.
                </p>
                <div className="grid grid-cols-4 gap-3">
                  <Field label="Пирамидинг">
                    <select value={form.pyramid_enabled ? '1' : '0'} onChange={e => setForm(f => ({ ...f, pyramid_enabled: e.target.value === '1' }))} className={inputCls}>
                      <option value="0">Выключен</option>
                      <option value="1">Включён</option>
                    </select>
                  </Field>
                  {form.pyramid_enabled && (
                    <>
                      <NumberField label="Максимум ордеров" value={form.pyramid_max_orders} onChange={v => setForm(f => ({ ...f, pyramid_max_orders: v }))} />
                      <NumberField label="Шаг добора (%, от последнего входа)" value={form.pyramid_step_percent} onChange={v => setForm(f => ({ ...f, pyramid_step_percent: v }))} step={0.01} />
                      <Field label="Размер ордеров">
                        <select
                          value={form.pyramid_size_progression}
                          onChange={e => setForm(f => ({ ...f, pyramid_size_progression: e.target.value as FormState['pyramid_size_progression'] }))}
                          className={inputCls}
                        >
                          <option value="decreasing">Убывающий</option>
                          <option value="fixed">Фиксированный (= первому ордеру)</option>
                        </select>
                      </Field>
                      {form.pyramid_size_progression === 'decreasing' && (
                        <NumberField label="Множитель убывания" value={form.pyramid_size_multiplier} onChange={v => setForm(f => ({ ...f, pyramid_size_multiplier: v }))} step={0.1} />
                      )}
                    </>
                  )}
                </div>
              </Section>

              <Section title="Take Profit / Stop Loss">
                <div className="grid grid-cols-4 gap-3">
                  <Field label="Take Profit">
                    <select value={form.tp_enabled ? '1' : '0'} onChange={e => setForm(f => ({ ...f, tp_enabled: e.target.value === '1' }))} className={inputCls}>
                      <option value="1">Включён</option>
                      <option value="0">Выключен</option>
                    </select>
                  </Field>
                  {form.tp_enabled && (
                    <NumberField label="TP (% от средней)" value={form.tp_percent} onChange={v => setForm(f => ({ ...f, tp_percent: v }))} step={0.01} />
                  )}
                  <Field label="Stop Loss">
                    <select value={form.sl_enabled ? '1' : '0'} onChange={e => setForm(f => ({ ...f, sl_enabled: e.target.value === '1' }))} className={inputCls}>
                      <option value="1">Включён</option>
                      <option value="0">Выключен</option>
                    </select>
                  </Field>
                  {form.sl_enabled && (
                    <NumberField label="SL (%)" value={form.sl_percent} onChange={v => setForm(f => ({ ...f, sl_percent: v }))} step={0.1} />
                  )}
                  <NumberField label="Max drawdown стоп (%)" value={form.max_drawdown_percent} onChange={v => setForm(f => ({ ...f, max_drawdown_percent: v }))} />
                </div>
              </Section>

              <Section title="Индикатор входа">
                <Field label="Стратегия">
                  <select
                    value={form.indicator}
                    onChange={e => setForm(f => ({ ...f, indicator: e.target.value as IndicatorStrategy }))}
                    className={inputCls}
                  >
                    {Object.entries(INDICATOR_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                </Field>
                <IndicatorFields form={form} setForm={setForm} />
              </Section>
            </>
          )}

          {parseError && (
            <div className="text-red-400 text-xs bg-red-900/30 border border-red-700 rounded px-2 py-1.5">
              {parseError}
            </div>
          )}

          <div className="flex items-center gap-3">
            <button
              onClick={handleRun}
              disabled={(!advancedMode ? false : !configText) || isRunning}
              className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded text-sm font-medium"
            >
              <Play size={14} />
              {isRunning ? 'Выполняется...' : 'Запустить бэктест'}
            </button>
            <p className="text-xs text-gray-500">
              Полный год данных может занимать 20+ минут. Для быстрого теста сузьте диапазон дат.
            </p>
          </div>
        </div>

        {/* Status */}
        {activeTaskId && (
          <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 space-y-2">
            {statusError && (
              <p className="text-yellow-400 text-sm">
                Статус этой задачи недоступен (сервис бэктестера мог перезапуститься). Проверьте вкладку истории ниже — возможно, прогон уже завершился.
              </p>
            )}
            {!statusError && status && (
              <>
                <div className="flex items-center gap-4">
                  <span className={`px-2 py-1 rounded text-xs font-medium ${
                    status.status === 'completed' ? 'bg-green-900 text-green-300' :
                    status.status === 'error' ? 'bg-red-900 text-red-300' :
                    'bg-yellow-900 text-yellow-300'
                  }`}>
                    {status.status.toUpperCase()}
                  </span>
                  {isRunning && <ElapsedTimer startTime={status.start_time} />}
                  {isRunning && <span className="text-xs text-gray-400">{status.progress}%</span>}
                  {status.status === 'error' && (
                    <span className="text-red-400 text-sm">{status.error}</span>
                  )}
                </div>
                {isRunning && (
                  <div className="w-full h-1.5 bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-blue-500 transition-all duration-500"
                      style={{ width: `${Math.max(4, status.progress)}%` }}
                    />
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* Results */}
        {results && activeTaskId && <ResultsView results={results} taskId={activeTaskId} />}

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
