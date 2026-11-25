'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useIsAuthed } from '@/lib/useSession';

export default function Home() {
  const router = useRouter();
  // после перезагрузки access-токена в памяти нет — сессию подтверждает refresh-cookie
  const authed = useIsAuthed();

  useEffect(() => {
    if (authed) router.replace('/dashboard');
  }, [authed, router]);

  // пока проверяем сессию или уже уходим в дашборд — пустой экран, без мигания кнопки
  if (authed !== false) return <div className="min-h-screen bg-gray-900" />;

  return (
    <main className="min-h-screen bg-gray-900 flex flex-col items-center justify-center gap-8 px-4">
      <h1 className="text-5xl font-bold tracking-tight text-white">kandle</h1>
      <Link
        href="/login"
        className="px-8 py-3 rounded-lg bg-blue-600 hover:bg-blue-700 text-lg font-medium text-white"
      >
        Войти
      </Link>
      <Link href="/ready-strategies" className="text-sm text-gray-400 hover:text-white">
        Готовые стратегии
      </Link>
    </main>
  );
}
