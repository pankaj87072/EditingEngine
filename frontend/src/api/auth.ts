import { request } from './client';

export const getAuthConfig = (signal?: AbortSignal) =>
  request<{ enabled: boolean }>('/auth/config', { signal, timeoutMs: 6000, retries: 0 });

export const login = (email: string, password: string) =>
  request<{ token: string; email: string }>('/auth/login', { method: 'POST', body: { email, password } });

export const register = (email: string, password: string) =>
  request<{ token: string; email: string }>('/auth/register', { method: 'POST', body: { email, password } });

export const getMe = (signal?: AbortSignal) => request<{ email: string }>('/auth/me', { signal, retries: 0 });
