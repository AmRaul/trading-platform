import axios, { InternalAxiosRequestConfig } from 'axios';
import { getAccessToken, goToLogin, refreshAccessToken } from './auth';
import type { Bot, BotPayload } from './types';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const SIGNALS_URL = process.env.NEXT_PUBLIC_SIGNALS_URL || 'http://localhost:8020';
const BACKTESTER_URL = process.env.NEXT_PUBLIC_BACKTESTER_URL || 'http://localhost:8010';

export const api = axios.create({
  baseURL: API_URL,
  headers: { 'Content-Type': 'application/json' },
});

export const signalsApi2 = axios.create({
  baseURL: SIGNALS_URL,
  headers: { 'Content-Type': 'application/json' },
});

export const backtesterApi2 = axios.create({
  baseURL: BACKTESTER_URL,
  headers: { 'Content-Type': 'application/json' },
});

// Токен kandle — во все три API: signals. и backtester. закрыты nginx-проверкой
// этого же токена (auth_request → /api/auth/verify)
type RetriableConfig = InternalAxiosRequestConfig & { _retried?: boolean };

for (const client of [api, signalsApi2, backtesterApi2]) {
  client.interceptors.request.use(async (config) => {
    if (config.url?.startsWith('/api/auth/')) return config;  // вход/обновление — без Bearer
    const token = await getAccessToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  });

  // 401 → один раз обновить access по refresh-cookie и повторить запрос; не вышло — на вход
  client.interceptors.response.use(
    (response) => response,
    async (error) => {
      const config = error.config as RetriableConfig | undefined;
      const isAuthCall = config?.url?.startsWith('/api/auth/');
      if (error.response?.status === 401 && config && !isAuthCall && typeof window !== 'undefined') {
        if (!config._retried) {
          config._retried = true;
          const token = await refreshAccessToken();
          if (token) {
            config.headers.Authorization = `Bearer ${token}`;
            return client(config);
          }
        }
        goToLogin();
      }
      return Promise.reject(error);
    }
  );
}

// Auth API — withCredentials: refresh-cookie ставится/снимается этими ответами
export const authApi = {
  register: (username: string, password: string) =>
    api.post('/api/auth/register', { username, password }, { withCredentials: true }),

  login: (username: string, password: string) =>
    api.post('/api/auth/login', { username, password }, { withCredentials: true }),

  logout: () => api.post('/api/auth/logout', null, { withCredentials: true }),
};

// Bots API
export const botsApi = {
  getAll: () => api.get<Bot[]>('/api/bots/'),

  getCryptorg: () => api.get('/api/bots/cryptorg'),

  getOne: (id: number) => api.get(`/api/bots/${id}`),

  create: (data: BotPayload) => api.post<Bot>('/api/bots/', data),

  update: (id: number, data: Partial<BotPayload>) => api.patch<Bot>(`/api/bots/${id}`, data),

  delete: (id: number) => api.delete(`/api/bots/${id}`),
};

// Trading API
export const tradingApi = {
  manualEntry: (bot_id: number, account_balance: number) =>
    api.post('/api/trading/entry', { bot_id, account_balance }),

  limitEntry: (bot_id: number, limit_price: number) =>
    api.post('/api/trading/entry/limit', { bot_id, limit_price }),

  signalEntry: (bot_id: number) =>
    api.post('/api/trading/entry/signal', { bot_id }),

  cancelLimit: (bot_id: number) =>
    api.post('/api/trading/entry/cancel', { bot_id }),

  manualClose: (bot_id: number) =>
    api.post('/api/trading/close', { bot_id }),
};

// Positions API
export const positionsApi = {
  getAll: (is_open?: boolean) =>
    api.get('/api/positions/', { params: { is_open } }),

  getByBot: (bot_id: number) =>
    api.get(`/api/positions/bot/${bot_id}`),

  setManaged: (position_id: number, is_bot_managed: boolean) =>
    api.patch(`/api/positions/${position_id}/managed`, { is_bot_managed }),

  setTrailingFrozen: (position_id: number, trailing_enabled: boolean) =>
    api.patch(`/api/positions/${position_id}/trailing`, { trailing_enabled }),
};

// Trades API
export const tradesApi = {
  getAll: () => api.get('/api/trades/'),

  getByBot: (bot_id: number) => api.get(`/api/trades/bot/${bot_id}`),
};

// Ready strategies API
export const readyStrategiesApi = {
  getAll: () => api.get('/api/ready-strategies/'),

  getOne: (slug: string) => api.get(`/api/ready-strategies/${slug}`),

  launch: (slug: string, data: {
    variant_key: string;
    deposit_usdt: number;
    exchange: 'cryptorg' | 'bybit' | 'paper';
    account_id?: number | null;
    bybit_account_id?: number | null;
  }) => api.post(`/api/ready-strategies/${slug}/launch`, data),
};

// Screener API — signals service
export const screenerApi = {
  getLatest: () => signalsApi2.get('/api/screener/latest'),
  triggerScan: () => signalsApi2.post('/api/screener/scan'),
};

// Signals API — signals service
export const signalsApi = {
  getAll: (limit = 100) => signalsApi2.get('/api/signals/', { params: { limit } }),
};

// Trend Signals API — signals service
export const trendSignalsApi = {
  getAll: (limit = 200) => signalsApi2.get('/api/trend-signals/', { params: { limit } }),
};

// Signal Strategies API — signals service
export const signalStrategiesApi = {
  getAll: () => signalsApi2.get('/api/signal-strategies/'),
  create: (data: {
    name: string;
    range_min?: number | null;
    range_max?: number | null;
    change_min?: number | null;
    change_max?: number | null;
    vol_1h_min?: number | null;
    side: string;
    description?: string;
  }) => signalsApi2.post('/api/signal-strategies/', data),
  update: (id: number, data: Partial<{
    range_min: number | null;
    range_max: number | null;
    change_min: number | null;
    change_max: number | null;
    vol_1h_min: number | null;
    side: string;
    description: string;
    is_active: boolean;
  }>) => signalsApi2.patch(`/api/signal-strategies/${id}`, data),
  delete: (id: number) => signalsApi2.delete(`/api/signal-strategies/${id}`),
};

// Trend Symbols API — signals service
export const trendSymbolsApi = {
  getAll: () => signalsApi2.get('/api/trend-symbols/'),
  add: (symbol: string) => signalsApi2.post('/api/trend-symbols/', { symbol }),
  remove: (id: number) => signalsApi2.delete(`/api/trend-symbols/${id}`),
};

// Backtester API — backtester-web service
export const backtestApi = {
  run: (config: object) => backtesterApi2.post('/api/run-backtest', config),
  getStatus: (taskId: string) => backtesterApi2.get(`/api/backtest-status/${taskId}`),
  getResults: (taskId: string) => backtesterApi2.get(`/api/backtest-results/${taskId}`),
  getHistory: (limit = 50) => backtesterApi2.get('/api/backtest-history', { params: { limit } }),
};

// Accounts API
export const accountsApi = {
  getAll: () => api.get('/api/accounts/'),
  create: (data: { name: string; webhook_url: string; api_key?: string; api_secret?: string }) =>
    api.post('/api/accounts/', data),
  update: (id: number, data: { name?: string; webhook_url?: string; api_key?: string; api_secret?: string }) =>
    api.put(`/api/accounts/${id}`, data),
  delete: (id: number) => api.delete(`/api/accounts/${id}`),
  // ключ Bybit счёта «Bybit-ликвидность»: работает ли и какие позиции видны
  check: (id: number) => api.post<AccountCheck>(`/api/accounts/${id}/check`),
  // счёт глазами биржи: все позиции и закрытые сделки, включая ручные
  exchange: (id: number, days = 30) => api.get<AccountExchange>(`/api/accounts/${id}/exchange`, { params: { days } }),
};

export interface AccountBotRef { bot_id: number; name: string }

export interface AccountExchange {
  ok: boolean;
  error?: string;
  days?: number;
  account?: { id: number; name: string };
  positions?: {
    symbol: string; side: 'LONG' | 'SHORT'; size: number; avg_price: number; mark_price: number;
    value_usdt: number; unrealized_pnl: number; leverage?: string; liq_price: number | null;
    stop_loss: number | null; take_profit: number | null; opened_at_ms: number | null; bot: AccountBotRef | null;
  }[];
  closed?: {
    symbol: string; side: 'LONG' | 'SHORT'; qty: number; entry_price: number; exit_price: number;
    value_usdt: number; pnl: number; leverage?: string; closed_at_ms: number; bot: AccountBotRef | null;
  }[];
  summary?: {
    open_positions: number; open_unrealized_pnl: number;
    closed: { count: number; pnl: number; by_bots: { count: number; pnl: number }; not_bots: { count: number; pnl: number } };
  };
}

export interface AccountCheck {
  ok: boolean;
  error?: string;
  read_only?: boolean;
  positions?: { symbol: string; side: 'LONG' | 'SHORT'; size: number; avg_price: number }[];
}

// Bybit Accounts API — direct Bybit API key trading, separate from Cryptorg
export const bybitAccountsApi = {
  getAll: () => api.get('/api/bybit-accounts/'),
  create: (data: { name: string; api_key: string; api_secret: string; testnet?: boolean }) =>
    api.post('/api/bybit-accounts/', data),
  update: (id: number, data: { name?: string; api_key?: string; api_secret?: string; testnet?: boolean }) =>
    api.put(`/api/bybit-accounts/${id}`, data),
  delete: (id: number) => api.delete(`/api/bybit-accounts/${id}`),
};

// Admin API — single-owner access, backend enforces via get_admin_user (403 for anyone else)
export const adminApi = {
  getStats: () => api.get('/api/admin/stats'),
  getUsers: () => api.get('/api/admin/users'),
  getBots: () => api.get('/api/admin/bots'),
  getHealth: () => api.get('/api/admin/health'),
};
