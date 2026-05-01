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
