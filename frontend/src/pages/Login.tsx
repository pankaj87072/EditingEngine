import { useState, type FormEvent } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { Button } from '@/components/Button';
import { Logo } from '@/components/Logo';
import { login, register } from '@/api/auth';
import { ApiError, friendlyMessage } from '@/api/client';
import { useAuth } from '@/lib/auth';

export default function Login({ mode }: { mode: 'login' | 'register' }) {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const auth = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isRegister = mode === 'register';
  const next = params.get('next') && params.get('next')!.startsWith('/') ? params.get('next')! : '/app';

  if (!auth.loading && !auth.enabled) return <Navigate to="/app" replace />;
  if (auth.signedIn) return <Navigate to={next} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await (isRegister ? register : login)(email.trim(), password);
      auth.signIn(res.token);
      nav(next, { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError && (err.status === 401 || err.status === 422) && err.message
          ? err.message
          : friendlyMessage(err),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-dvh place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <Link to="/" className="mb-8 block text-center" aria-label="AutoVideoGen home">
          <Logo />
        </Link>
        <form onSubmit={submit} className="card space-y-5 p-6" noValidate>
          <div>
            <h1 className="text-2xl font-bold">{isRegister ? 'Create your account' : 'Welcome back'}</h1>
            <p className="mt-1 text-sm text-mute">
              {isRegister ? 'Your Reels are saved to your account and available on any device.' : 'Sign in to see your Reels.'}
            </p>
          </div>
          <div>
            <label htmlFor="email" className="mb-1.5 block text-sm font-medium">Email</label>
            <input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="field" />
          </div>
          <div>
            <label htmlFor="password" className="mb-1.5 block text-sm font-medium">Password</label>
            <input
              id="password"
              type="password"
              autoComplete={isRegister ? 'new-password' : 'current-password'}
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-describedby={isRegister ? 'pw-hint' : undefined}
              className="field"
            />
            {isRegister && <p id="pw-hint" className="mt-1.5 text-xs text-mute">At least 8 characters.</p>}
          </div>
          {error && <p role="alert" className="text-sm text-bad">{error}</p>}
          <Button type="submit" size="lg" className="w-full" disabled={busy || !email || !password}>
            {busy ? 'Please wait…' : isRegister ? 'Create account' : 'Sign in'}
          </Button>
          <p className="text-center text-sm text-mute">
            {isRegister ? 'Already have an account? ' : 'New here? '}
            <Link to={isRegister ? '/login' : '/register'} className="text-azure hover:underline">
              {isRegister ? 'Sign in' : 'Create an account'}
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
