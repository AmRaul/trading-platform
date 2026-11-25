'use client';

import { useEffect, useState } from 'react';
import { getAccessToken, onAccessTokenChange } from './auth';

/** null — ещё проверяем (тихий refresh), true/false — вошёл или гость. Без редиректа на вход. */
export function useIsAuthed(): boolean | null {
  const [authed, setAuthed] = useState<boolean | null>(null);
  useEffect(() => {
    getAccessToken().then((t) => setAuthed(!!t));
    const off = onAccessTokenChange((t) => setAuthed(!!t));
    return () => { off(); };
  }, []);
  return authed;
}
