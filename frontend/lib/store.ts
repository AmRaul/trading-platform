import { create } from 'zustand';
import { setAccessToken } from './auth';
import { authApi } from './api';

interface User {
  username: string;
  token?: string;  // access-токен: уходит в память lib/auth, в localStorage не пишется
}

interface AuthState {
  user: User | null;
  setUser: (user: User | null) => void;
  logout: () => void;
  hydrate: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  // null и на сервере, и в первом рендере клиента — иначе расхождение гидратации (React #418);
  // имя из localStorage подставляет hydrate() после монтирования (app/providers.tsx)
  user: null,
  hydrate: () => {
    try {
      const username = localStorage.getItem('username');
      if (username) set({ user: { username } });  // имя — для шапки; сессию подтверждает refresh
    } catch {}
  },
  setUser: (user) => {
    set({ user: user ? { username: user.username } : null });
    setAccessToken(user?.token ?? null);
    try {
      if (user) localStorage.setItem('username', user.username);
      else localStorage.removeItem('username');
    } catch {}
  },
  logout: () => {
    set({ user: null });
    setAccessToken(null);
    try { localStorage.removeItem('username'); } catch {}
    authApi.logout().catch(() => {});  // снять refresh-cookie на сервере
  },
}));

interface PriceState {
  prices: Record<string, number>;
  updatePrice: (symbol: string, price: number) => void;
}

export const usePriceStore = create<PriceState>((set) => ({
  prices: {},
  updatePrice: (symbol, price) =>
    set((state) => ({
      prices: { ...state.prices, [symbol]: price },
    })),
}));

interface PositionData {
  average_price: number | null;
  current_sl: number | null;
  total_size: number;
  order_count: number;
  unrealized_pnl: number;
  last_order_price: number | null;
}

interface PositionState {
  positions: Record<number, PositionData>;
  setPosition: (botId: number, data: PositionData) => void;
  updatePositionFields: (botId: number, fields: Partial<PositionData>) => void;
  clearPosition: (botId: number) => void;
}

export const usePositionStore = create<PositionState>((set) => ({
  positions: {},
  setPosition: (botId, data) =>
    set((state) => ({
      positions: { ...state.positions, [botId]: data },
    })),
  updatePositionFields: (botId, fields) =>
    set((state) => {
      const existing = state.positions[botId] ?? {
        average_price: null,
        current_sl: null,
        total_size: 0,
        order_count: 0,
        unrealized_pnl: 0,
        last_order_price: null,
      };
      return {
        positions: { ...state.positions, [botId]: { ...existing, ...fields } },
      };
    }),
  clearPosition: (botId) =>
    set((state) => {
      const next = { ...state.positions };
      delete next[botId];
      return { positions: next };
    }),
}));
