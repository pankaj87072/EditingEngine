import { useEffect } from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';
import { ApiError } from '@/api/client';
import { getStatus, listJobs, type ServerJob } from '@/api/jobs';
import { addProject, getProjectRecord, useProjectRecords } from '@/lib/projects';
import { titleFromScript } from '@/utils/script';
import { parseServerDate } from '@/utils/format';
import type { JobStatus, ProjectRecord } from '@/types';

export interface ProjectView extends ProjectRecord {
  status?: JobStatus;
  /** 'missing' = server no longer knows this job (deleted/expired) */
  load: 'loading' | 'ok' | 'missing' | 'error';
}

function recordFromServer(j: ServerJob): ProjectRecord {
  return {
    jobId: j.job_id,
    title: titleFromScript(j.script),
    script: j.script,
    settings: {
      ttsProvider: j.tts_provider,
      editingStyle: j.editing_style ?? 'clean',
      intensity: j.intensity,
      captionStyle: j.caption_style,
      subtitlePosition: j.subtitle_position,
    },
    clipCount: j.clip_count,
    createdAt: parseServerDate(j.created_at).toISOString(),
  };
}

export function useProjects(limit?: number) {
  // Server history is the source of truth: Reels made on other devices (or before
  // the browser cache was cleared) are folded into the local list.
  const server = useQuery({ queryKey: ['jobs'], queryFn: ({ signal }) => listJobs(signal), staleTime: 15_000, retry: 1 });
  useEffect(() => {
    server.data?.jobs.forEach((j) => {
      if (!getProjectRecord(j.job_id)) addProject(recordFromServer(j));
    });
  }, [server.data]);

  const records = useProjectRecords();
  const sorted = [...records].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  const shown = limit ? sorted.slice(0, limit) : sorted;

  const queries = useQueries({
    queries: shown.map((p) => ({
      queryKey: ['job', p.jobId],
      queryFn: ({ signal }: { signal: AbortSignal }) => getStatus(p.jobId, signal),
      retry: (n: number, err: unknown) => !(err instanceof ApiError && err.status === 404) && n < 2,
      staleTime: 15_000,
      refetchInterval: (q: { state: { data?: JobStatus } }) =>
        q.state.data && (q.state.data.status === 'pending' || q.state.data.status === 'processing') ? 3000 : false,
    })),
  });

  const projects: ProjectView[] = shown.map((p, i) => {
    const q = queries[i];
    const missing = q.error instanceof ApiError && q.error.status === 404;
    return {
      ...p,
      status: q.data,
      load: q.data ? 'ok' : missing ? 'missing' : q.isError ? 'error' : 'loading',
    };
  });

  return { projects, loadingServer: server.isPending, total: records.length, refetchAll: () => queries.forEach((q) => void q.refetch()) };
}
