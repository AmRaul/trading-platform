'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/lib/store';
import { LogOut, User } from 'lucide-react';

export default function Navbar() {
  const router = useRouter();
  const { user, logout } = useAuthStore();

  const handleLogout = () => {
    logout();
    router.push('/login');
  };

  return (
    <nav className="bg-gray-800 border-b border-gray-700">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center space-x-8">
            <Link href="/dashboard" className="text-xl font-bold">
              Trading Dashboard
            </Link>

            <div className="flex space-x-4">
              <Link
                href="/dashboard"
                className="px-3 py-2 rounded hover:bg-gray-700"
              >
                Dashboard
              </Link>
              <Link
                href="/bots"
                className="px-3 py-2 rounded hover:bg-gray-700"
              >
                Bots
              </Link>
              <Link
                href="/positions"
                className="px-3 py-2 rounded hover:bg-gray-700"
              >
                Positions
              </Link>
              <Link
                href="/history"
                className="px-3 py-2 rounded hover:bg-gray-700"
              >
                History
              </Link>
              <Link
                href="/screener"
                className="px-3 py-2 rounded hover:bg-gray-700"
              >
                Screener
              </Link>
              <Link
                href="/signals"
                className="px-3 py-2 rounded hover:bg-gray-700"
              >
                Signals
              </Link>
              <Link
                href="/trend-signals"
                className="px-3 py-2 rounded hover:bg-gray-700"
              >
                Trend
              </Link>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <Link
              href="/profile"
              className="flex items-center gap-1.5 px-3 py-2 rounded hover:bg-gray-700 text-gray-400 hover:text-white text-sm"
            >
              <User size={16} />
              {user?.username}
            </Link>
            <button
              onClick={handleLogout}
              className="p-2 rounded hover:bg-gray-700"
              title="Logout"
            >
              <LogOut size={20} />
            </button>
          </div>
        </div>
      </div>
    </nav>
  );
}
