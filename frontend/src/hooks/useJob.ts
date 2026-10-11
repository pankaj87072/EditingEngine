import { useQuery } from '@tanstack/react-query';
import { ApiError } from '@/api/client';
import { getPlan, getResult, getStatus } from '@/api/jobs';

const ACTIVE = new Set(['pending', 'processing']);

/** Polls the real backend status while the job is running (paused in background tabs). */
export function useJob(jobId: string | undefined, intervalMs = 1500) {
  return useQuery({
    queryKey: ['job', jobId],
    queryFn: ({ signal }) => getStatus(jobId!, signal),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data && ACTIVE.has(q.state.data.status) ? intervalMs : false),
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 4,
    retryDelay: (n) => Math.min(1000 * 2 ** n, 8000),
    staleTime: 2000,
  });
}

export function useJobResult(jobId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ['result', jobId],
    queryFn: ({ signal }) => getResult(jobId!, signal),
    enabled: !!jobId && enabled,
    staleTime: 60_000,
  });
}

export function useJobPlan(jobId: string | undefined) {
  return useQuery({
    queryKey: ['plan', jobId],
    queryFn: ({ signal }) => getPlan(jobId!, signal),
    enabled: !!jobId,
    staleTime: Infinity,
    retry: false,
  });
}
