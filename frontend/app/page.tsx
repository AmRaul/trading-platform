'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/lib/store';
import { getAccessToken } from '@/lib/auth';

export default function Home() {
  const router = useRouter();
  const user = useAuthStore((state) => state.user);

  useEffect(() => {
    // после перезагрузки access-токена в памяти нет — сессию подтверждает refresh-cookie
    getAccessToken().then((token) => router.push(token ? '/dashboard' : '/login'));
  }, [user, router]);

  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="text-xl">Loading...</div>
    </div>
  );
}
