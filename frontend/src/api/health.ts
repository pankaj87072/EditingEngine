import type { HealthInfo } from '@/types';
import { request } from './client';

export const getHealth = (signal?: AbortSignal) => request<HealthInfo>('/health', { signal, timeoutMs: 6000, retries: 0 });
