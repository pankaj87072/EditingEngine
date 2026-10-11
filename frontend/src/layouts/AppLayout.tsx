import { NavLink, Navigate, Outlet, Link, useLocation } from 'react-router-dom';
import { CreditCard, History, LayoutGrid, LogOut, Plus, Settings } from 'lucide-react';
import { useAuth } from '@/lib/auth';
import { Logo } from '@/components/Logo';
import { buttonClasses } from '@/components/Button';
import { cn } from '@/lib/cn';

const nav = [
  { to: '/app', label: 'Dashboard', icon: LayoutGrid, end: true },
  { to: '/app/history', label: 'History', icon: History },
  { to: '/app/settings', label: 'Settings', icon: Settings },
  { to: '/app/pricing', label: 'Pricing', icon: CreditCard },
];

export function AppLayout() {
  const auth = useAuth();
  const loc = useLocation();

  if (auth.loading) {
    return (
      <div className="grid min-h-dvh place-items-center" role="status" aria-label="Loading">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-line border-t-violet" />
      </div>
    );
  }
  if (auth.enabled && !auth.signedIn) {
    return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  }

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[15.5rem_1fr]">
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh flex-col border-r border-line bg-surface/60 p-4 lg:flex">
        <Link to="/" className="px-2 py-3" aria-label="AutoVideoGen home">
          <Logo />
        </Link>
        <Link to="/app/new" className={buttonClasses('primary', 'md', 'mt-5 w-full')}>
          <Plus size={18} aria-hidden /> New Reel
        </Link>
        <nav aria-label="Main" className="mt-6 flex flex-col gap-1">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors',
                  isActive ? 'bg-raised text-ink' : 'text-mute hover:bg-raised/60 hover:text-ink',
                )
              }
            >
              <Icon size={18} aria-hidden /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto space-y-2 px-1">
          {auth.enabled && (
            <div className="rounded-xl border border-line p-3 text-xs">
              <p className="truncate text-mute" title={auth.email}>{auth.email ?? 'Signed in'}</p>
              <button type="button" onClick={auth.signOut} className="mt-2 inline-flex items-center gap-1.5 font-medium text-ink hover:text-bad">
                <LogOut size={13} aria-hidden /> Sign out
              </button>
            </div>
          )}
          <p className="px-2 text-xs leading-relaxed text-mute/70">Output: 1080×1920 vertical MP4</p>
        </div>
      </aside>

      {/* Mobile top bar */}
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-line bg-bg/90 px-4 py-3 backdrop-blur lg:hidden">
        <Link to="/" aria-label="AutoVideoGen home">
          <Logo />
        </Link>
      </header>

      <main className="min-w-0 px-4 pb-28 pt-6 sm:px-8 lg:px-10 lg:pb-12 lg:pt-10">
        <div className="mx-auto w-full max-w-6xl">
          <Outlet />
        </div>
      </main>

      {/* Mobile bottom navigation */}
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
      >
        {[nav[0], { to: '/app/new', label: 'New', icon: Plus }, nav[1], nav[2]].map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/app'}
            className={({ isActive }) =>
              cn('flex min-h-[3.5rem] flex-col items-center justify-center gap-1 text-xs font-medium', isActive ? 'text-ink' : 'text-mute')
            }
          >
            {to === '/app/new' ? (
              <span className="brand-gradient grid h-8 w-8 place-items-center rounded-xl text-white">
                <Icon size={18} aria-hidden />
              </span>
            ) : (
              <Icon size={20} aria-hidden />
            )}
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
