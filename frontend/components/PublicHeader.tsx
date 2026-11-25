'use client';

import Link from 'next/link';

/** Шапка для гостя на открытых страницах: без меню закрытых разделов. */
export default function PublicHeader() {
  return (
    <nav className="bg-gray-800 border-b border-gray-700">
      <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">
        <Link href="/ready-strategies" className="text-lg font-bold text-white">kandle</Link>
        <Link href="/login" className="px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-sm font-medium">
          Войти
        </Link>
      </div>
    </nav>
  );
}
