import { create } from 'zustand';

interface User {
  username: string;
  token: string;
}

interface AuthState {
  user: User | null;
  setUser: (user: User | null) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  setUser: (user) => {
    set({ user });
    if (user) {
      localStorage.setItem('token', user.token);
      localStorage.setItem('username', user.username);
    } else {
      localStorage.removeItem('token');
      localStorage.removeItem('username');
    }
  },
  logout: () => {
    set({ user: null });
    localStorage.removeItem('token');
    localStorage.removeItem('username');
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
