'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { CandlestickChart, ArrowRight } from 'lucide-react';
import { useIsAuthed } from '@/lib/useSession';

export default function Home() {
  const router = useRouter();
  // после перезагрузки access-токена в памяти нет — сессию подтверждает refresh-cookie
  const authed = useIsAuthed();

  useEffect(() => {
    if (authed) router.replace('/dashboard');
  }, [authed, router]);

  // пока проверяем сессию или уже уходим в дашборд — пустой экран, без мигания кнопки
  if (authed !== false) return <div className="min-h-screen bg-gray-950" />;

  return (
    <main className="relative min-h-screen overflow-hidden bg-gray-950 text-white flex items-center justify-center px-4">
      {/* мягкое свечение и сетка на фоне */}
      <div className="pointer-events-none absolute -top-40 left-1/2 h-[36rem] w-[36rem] -translate-x-1/2 rounded-full bg-blue-600/20 blur-3xl" />
      <div className="pointer-events-none absolute bottom-[-12rem] right-[-8rem] h-[28rem] w-[28rem] rounded-full bg-emerald-500/10 blur-3xl" />
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.07]"
        style={{
          backgroundImage:
            'linear-gradient(to right, #fff 1px, transparent 1px), linear-gradient(to bottom, #fff 1px, transparent 1px)',
          backgroundSize: '48px 48px',
          maskImage: 'radial-gradient(ellipse at center, black 30%, transparent 75%)',
          WebkitMaskImage: 'radial-gradient(ellipse at center, black 30%, transparent 75%)',
        }}
      />

      <div className="relative flex flex-col items-center text-center">
        <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-emerald-400 shadow-lg shadow-blue-500/30">
          <CandlestickChart size={32} className="text-white" />
        </div>
        <h1 className="text-5xl sm:text-6xl font-semibold tracking-tight">kandle</h1>
        <p className="mt-3 text-gray-400 text-base sm:text-lg">Торговые боты, проверенные на истории</p>

        <div className="mt-10 flex flex-col sm:flex-row items-center gap-3">
          <Link
            href="/login"
            className="group inline-flex items-center gap-2 rounded-xl bg-blue-600 px-8 py-3 text-base font-medium shadow-lg shadow-blue-600/30 transition hover:bg-blue-500"
          >
            Войти
            <ArrowRight size={18} className="transition group-hover:translate-x-0.5" />
          </Link>
          <Link
            href="/ready-strategies"
            className="rounded-xl border border-white/10 bg-white/5 px-8 py-3 text-base font-medium text-gray-200 backdrop-blur transition hover:border-white/20 hover:bg-white/10"
          >
            Готовые стратегии
          </Link>
        </div>
      </div>
    </main>
  );
}
