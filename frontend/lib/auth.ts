import axios from 'axios';

/**
 * Сессия kandle.
 * access-токен (30 мин) — только в памяти вкладки, в заголовке Authorization;
 * refresh-токен (30 дней) — httpOnly-cookie на /api/auth, JS его не видит.
 * Перезагрузка страницы или истёкший access → тихий POST /api/auth/refresh.
 */
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

let accessToken: string | null = null;
let refreshing: Promise<string | null> | null = null;
const listeners = new Set<(token: string | null) => void>();

if (typeof window !== 'undefined') {
  // долгий токен из прошлой версии больше не нужен — refresh-cookie его заменяет
  try { localStorage.removeItem('token'); } catch {}
}

export function setAccessToken(token: string | null) {
  accessToken = token;
  listeners.forEach((cb) => cb(token));
}

export function onAccessTokenChange(cb: (token: string | null) => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** Новый access по refresh-cookie; параллельные вызовы ждут один запрос. null — сессии нет. */
export function refreshAccessToken(): Promise<string | null> {
  if (!refreshing) {
    refreshing = axios
      .post(`${API_URL}/api/auth/refresh`, null, { withCredentials: true })
      .then((r) => r.data.access_token as string)
      .catch(() => null)
      .then((token) => {
        setAccessToken(token);
        return token;
      })
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

export async function getAccessToken(): Promise<string | null> {
  return accessToken ?? refreshAccessToken();
}

export function goToLogin() {
  setAccessToken(null);
  try { localStorage.removeItem('username'); } catch {}
  if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
    window.location.href = '/login';
  }
}
