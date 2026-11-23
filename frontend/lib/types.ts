// Типы ответов API kandle — зеркало схем backend/app/schemas/bot.py и routes/*accounts.py.
// Меняешь схему на бэкенде — поправь и здесь.

export type Exchange = 'cryptorg' | 'bybit' | 'paper';
export type Side = 'LONG' | 'SHORT';
export type BotSide = Side | 'NEUTRAL';  // NEUTRAL — straddle
export type BotType = 'pyramiding' | 'dca' | 'straddle';
export type BotStateName = 'IDLE' | 'WAITING' | 'SIGNAL' | 'ENTRY' | 'PYRAMIDING' | 'EXIT' | 'STRADDLE';

/** EntrySignalConfig: вход по сигналу MRC / SuperTrend с фильтром тренда */
export interface EntrySignal {
  type: 'mrc' | 'supertrend' | 'donchian';
  timeframe: string;
  st_period?: number;
  st_mult?: number;
  mrc_length?: number;
  mrc_inner_mult?: number;
  mrc_outer_mult?: number;
  mrc_gradsize?: number;
  mrc_source?: 'hlc3' | 'close' | 'ohlc4';
  entry_band: number;
  trend_ema_period: number | null;
  trend_ema_fast?: number | null;
  trend_timeframe: string;  // '60' | '240' | 'D'
  donchian_entry_days?: number;
  donchian_exit_days?: number;
}

/** StrategyConfig */
export interface BotConfig {
  bot_type?: BotType;
  order_count: number;
  entry_size_usdt: number;
  step_percent: number;
  leverage: number;
  pyramiding_multiplier: number;
  sl_after_order3: number;
  sl_breakeven_on_order2: boolean;
  sl_breakeven_plus: number;
  dca_multiplier: number;
  dca_multiplier_price: number;
  sl_initial: number | null;
  use_trailing: boolean;
  trailing_percent: number;
  tp_percent: number;
  cycle: boolean;
  entry_signal?: EntrySignal | null;
  phase2_after_steps?: number;
  add_stop_steps?: number;
  time_stop_minutes?: number | null;
  max_rearms?: number;
}

/** OpenPositionData */
export interface OpenPosition {
  id: number | null;
  average_price: number | null;
  current_sl: number | null;
  total_size: number;
  order_count: number;
  unrealized_pnl: number;
  last_order_price: number | null;
  opened_at: string;
}

/** StraddleState (domain/trading/straddle.py) + поле price из живого снимка */
export interface StraddleState {
  anchor: number;
  started_at: number;               // epoch, сек
  legs: Record<Side, [number, number][]>;  // [цена, USDT] ордеров стороны
  working: Side | null;
  adds: number;
  phase: number;
  stop: number;
  extreme: number;
  rearms: number;
  reset_needed: boolean;
  cycle_realized: number;
  realized: number;
  done: boolean;
  exit_reason: string;
  price?: number;
}

/** BotResponse */
export interface Bot {
  id: number;
  name: string;
  symbol: string;
  side: BotSide;
  config: BotConfig;
  state: BotStateName;
  is_active: boolean;
  total_pnl: number;
  exchange: Exchange;
  account_id: number | null;
  bybit_account_id: number | null;
  limit_entry_price: number | null;
  straddle: StraddleState | null;
  created_at: string;
  started_at: string | null;
  open_position: OpenPosition | null;
}

/** Тело POST /api/bots/ и PATCH /api/bots/{id} */
export interface BotPayload {
  name: string;
  symbol: string;
  side: BotSide;
  config: BotConfig;
  exchange: Exchange;
  account_id: number | null;
  bybit_account_id: number | null;
}

export interface CryptorgAccount {
  id: number;
  name: string;
  webhook_url_hint: string;
  has_api_key: boolean;
  has_api_secret: boolean;
}

export interface BybitAccount {
  id: number;
  name: string;
  api_key_hint: string;
  testnet: boolean;
}

/** События WebSocket по ботам (services/websocket.py → broadcast_event) */
/** add_pyramiding_order.py → "pyramiding_order_added" */
export interface PyramidingOrderEvent {
  bot_id: number;
  symbol: string;
  side: Side;
  order_number: number;
  price: number;
  new_average_price: number;
  new_sl: number;
  total_size: number;
  last_order_price?: number;
  unrealized_pnl?: number;
}

export interface TrailingStopEvent {
  bot_id: number;
  new_sl: number;
  unrealized_pnl: number;
}

export interface BotEvent {
  bot_id: number;
}

export interface PriceUpdateEvent {
  symbol: string;
  price: number;
}

/** Ошибка axios с detail от FastAPI (строка или список ошибок валидации) */
export function apiErrorText(error: unknown, fallback = 'Ошибка запроса'): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (Array.isArray(detail)) return detail.map((e: { msg?: string }) => e.msg ?? '').join(', ');
  return typeof detail === 'string' ? detail : fallback;
}
