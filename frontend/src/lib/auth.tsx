import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getAuthConfig, getMe } from '@/api/auth';
import { getToken, setToken, UNAUTHORIZED_EVENT } from '@/api/token';
import { clearProjects } from './projects';

interface AuthCtx {
  /** Server requires accounts. False while loading or when the server has them off. */
  enabled: boolean;
  loading: boolean;
  signedIn: boolean;
  email?: string;
  signIn: (token: string) => void;
  signOut: () => void;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [token, setTok] = useState<string | null>(getToken());
  const config = useQuery({ queryKey: ['auth-config'], queryFn: ({ signal }) => getAuthConfig(signal), staleTime: 5 * 60_000, retry: 1 });
  const enabled = !!config.data?.enabled;
  const me = useQuery({ queryKey: ['me', token], queryFn: ({ signal }) => getMe(signal), enabled: enabled && !!token, retry: false, staleTime: 60_000 });

  const signOut = useCallback(() => {
    setToken(null);
    setTok(null);
    clearProjects(); // local list belongs to the previous account
    qc.clear();
  }, [qc]);

  const signIn = useCallback(
    (t: string) => {
      setToken(t);
      setTok(t);
      clearProjects();
      qc.clear();
    },
    [qc],
  );

  // Any 401 from the API (expired/invalid token) signs the user out.
  useEffect(() => {
    const on = () => signOut();
    window.addEventListener(UNAUTHORIZED_EVENT, on);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, on);
  }, [signOut]);

  const value = useMemo<AuthCtx>(
    () => ({ enabled, loading: config.isPending, signedIn: !!token, email: me.data?.email, signIn, signOut }),
    [enabled, config.isPending, token, me.data?.email, signIn, signOut],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth must be used inside AuthProvider');
  return v;
}
