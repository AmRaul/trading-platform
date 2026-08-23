'use client';

import { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import { useRouter, usePathname } from 'next/navigation';
import { useAuthStore } from '@/lib/store';
import { LogOut, User, Menu, X, ChevronDown } from 'lucide-react';

const NAV_GROUPS = [
  {
    label: 'Trading',
    links: [
      { href: '/dashboard', label: 'Dashboard' },
      { href: '/bots', label: 'Bots' },
      { href: '/positions', label: 'Positions' },
      { href: '/history', label: 'History' },
    ],
  },
  {
    label: 'Market',
    links: [
      { href: '/screener', label: 'Screener' },
      { href: '/signals', label: 'Signals' },
      { href: '/signal-strategies', label: 'Strategies' },
      { href: '/trend-signals', label: 'Trend' },
      { href: '/trend-symbols', label: 'Symbols' },
    ],
  },
  {
    label: 'Setup',
    links: [
      { href: '/accounts', label: 'Accounts' },
      { href: '/backtester', label: 'Backtester' },
    ],
  },
];

function NavDropdown({ group, isActive }: { group: typeof NAV_GROUPS[number]; isActive: boolean }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const pathname = usePathname();

  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className={`flex items-center gap-1 px-3 py-2 rounded text-sm hover:bg-gray-700 ${
          isActive ? 'bg-gray-700 text-white' : 'text-gray-300'
        }`}
      >
        {group.label}
        <ChevronDown size={14} className={open ? 'rotate-180 transition-transform' : 'transition-transform'} />
      </button>
      {open && (
        <div className="absolute left-0 top-full mt-1 min-w-[160px] bg-gray-800 border border-gray-700 rounded-lg shadow-lg py-1 z-50">
          {group.links.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              onClick={() => setOpen(false)}
              className={`block px-3 py-2 text-sm ${
                pathname === href ? 'bg-gray-700 text-white' : 'text-gray-300 hover:bg-gray-700'
              }`}
            >
              {label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Navbar() {
  const router = useRouter();
  const pathname = usePathname();
  const { user, logout } = useAuthStore();
  const [mobileOpen, setMobileOpen] = useState(false);

  const handleLogout = () => {
    logout();
    router.push('/login');
  };

  return (
    <nav className="bg-gray-800 border-b border-gray-700">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-6 min-w-0">
            <Link href="/dashboard" className="text-xl font-bold shrink-0">
              Trading Dashboard
            </Link>

            <div className="hidden md:flex items-center gap-1">
              {NAV_GROUPS.map(group => (
                <NavDropdown
                  key={group.label}
                  group={group}
                  isActive={group.links.some(l => l.href === pathname)}
                />
              ))}
            </div>
          </div>

          <div className="hidden md:flex items-center gap-2 shrink-0">
            <span className="flex items-center gap-1.5 px-3 py-2 text-gray-400 text-sm">
              <User size={16} />
              {user?.username}
            </span>
            <button
              onClick={handleLogout}
              className="p-2 rounded hover:bg-gray-700"
              title="Logout"
            >
              <LogOut size={20} />
            </button>
          </div>

          <button
            onClick={() => setMobileOpen(o => !o)}
            className="md:hidden p-2 rounded hover:bg-gray-700"
            aria-label={mobileOpen ? 'Закрыть меню' : 'Открыть меню'}
            aria-expanded={mobileOpen}
          >
            {mobileOpen ? <X size={22} /> : <Menu size={22} />}
          </button>
        </div>
      </div>

      {mobileOpen && (
        <div className="md:hidden border-t border-gray-700 px-4 py-3 space-y-4 max-h-[calc(100vh-4rem)] overflow-y-auto">
          {NAV_GROUPS.map(group => (
            <div key={group.label}>
              <p className="text-[11px] uppercase tracking-wide text-gray-500 px-3 mb-1">{group.label}</p>
              <div className="space-y-1">
                {group.links.map(({ href, label }) => (
                  <Link
                    key={href}
                    href={href}
                    onClick={() => setMobileOpen(false)}
                    className={`block px-3 py-2 rounded text-sm ${
                      pathname === href ? 'bg-gray-700 text-white' : 'text-gray-300 hover:bg-gray-700'
                    }`}
                  >
                    {label}
                  </Link>
                ))}
              </div>
            </div>
          ))}

          <div className="border-t border-gray-700 pt-3 flex items-center justify-between">
            <span className="flex items-center gap-1.5 px-3 py-2 text-gray-400 text-sm">
              <User size={16} />
              {user?.username}
            </span>
            <button
              onClick={() => { setMobileOpen(false); handleLogout(); }}
              className="flex items-center gap-1.5 px-3 py-2 rounded hover:bg-gray-700 text-sm text-gray-300"
            >
              <LogOut size={18} /> Logout
            </button>
          </div>
        </div>
      )}
    </nav>
  );
}
