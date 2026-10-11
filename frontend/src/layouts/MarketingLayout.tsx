import { Link, Outlet } from 'react-router-dom';
import { Logo } from '@/components/Logo';
import { buttonClasses } from '@/components/Button';
import { useAuth } from '@/lib/auth';

export function MarketingLayout() {
  const auth = useAuth();
  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-30 border-b border-line/60 bg-bg/80 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-8">
          <Link to="/" aria-label="AutoVideoGen home">
            <Logo />
          </Link>
          <nav aria-label="Site" className="hidden items-center gap-7 text-sm text-mute md:flex">
            <a href="/#how" className="hover:text-ink">How it works</a>
            <a href="/#features" className="hover:text-ink">Features</a>
            <a href="/#faq" className="hover:text-ink">FAQ</a>
            <Link to="/app/pricing" className="hover:text-ink">Pricing</Link>
          </nav>
          <div className="flex items-center gap-2">
            {auth.enabled && !auth.signedIn ? (
              <Link to="/login" className={buttonClasses('ghost', 'sm')}>Sign in</Link>
            ) : (
              <Link to="/app" className={buttonClasses('ghost', 'sm', 'hidden sm:inline-flex')}>Open app</Link>
            )}
            <Link to="/app/new" className={buttonClasses('primary', 'sm')}>Create a Reel</Link>
          </div>
        </div>
      </header>
      <Outlet />
      <footer className="mt-24 border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-10 sm:flex-row sm:items-center sm:justify-between sm:px-8">
          <div>
            <Logo />
            <p className="mt-2 max-w-sm text-sm text-mute">Turn raw clips and a script into a vertical short-form video.</p>
          </div>
          <nav aria-label="Footer" className="flex gap-6 text-sm text-mute">
            <Link to="/app" className="hover:text-ink">Dashboard</Link>
            <Link to="/app/new" className="hover:text-ink">Create a Reel</Link>
            <Link to="/app/pricing" className="hover:text-ink">Pricing</Link>
          </nav>
        </div>
        <p className="border-t border-line py-5 text-center text-xs text-mute/70">© {new Date().getFullYear()} AutoVideoGen</p>
      </footer>
    </div>
  );
}
