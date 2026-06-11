import axios from 'axios';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const SIGNALS_URL = process.env.NEXT_PUBLIC_SIGNALS_URL || 'http://localhost:8020';

export const api = axios.create({
  baseURL: API_URL,
  headers: { 'Content-Type': 'application/json' },
});

export const signalsApi2 = axios.create({
  baseURL: SIGNALS_URL,
  headers: { 'Content-Type': 'application/json' },
});

// Add auth token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Auth API
export const authApi = {
  register: (username: string, password: string) =>
    api.post('/api/auth/register', { username, password }),

  login: (username: string, password: string) =>
    api.post('/api/auth/login', { username, password }),
};

// Bots API
export const botsApi = {
  getAll: () => api.get('/api/bots/'),

  getCryptorg: () => api.get('/api/bots/cryptorg'),

  getOne: (id: number) => api.get(`/api/bots/${id}`),

  create: (data: any) => api.post('/api/bots/', data),

  update: (id: number, data: any) => api.patch(`/api/bots/${id}`, data),

  delete: (id: number) => api.delete(`/api/bots/${id}`),
};

// Trading API
export const tradingApi = {
  manualEntry: (bot_id: number, account_balance: number) =>
    api.post('/api/trading/entry', { bot_id, account_balance }),

  manualClose: (bot_id: number) =>
    api.post('/api/trading/close', { bot_id }),
};

// Positions API
export const positionsApi = {
  getAll: (is_open?: boolean) =>
    api.get('/api/positions/', { params: { is_open } }),

  getByBot: (bot_id: number) =>
    api.get(`/api/positions/bot/${bot_id}`),
};

// Trades API
export const tradesApi = {
  getAll: () => api.get('/api/trades'),

  getByBot: (bot_id: number) => api.get(`/api/trades/bot/${bot_id}`),
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

// Profile API
export const profileApi = {
  getCredentials: () => api.get('/api/profile/credentials'),
  saveCredentials: (data: { exchange: string; webhook_url: string; api_key?: string; api_secret?: string }) =>
    api.put('/api/profile/credentials', data),
};
