import type { ClipItem, EditingPlan, JobResult, JobStatus, ReelSettings } from '@/types';
import { absoluteUrl, postForm, request } from './client';
import { withToken } from './token';

export interface CreateJobInput {
  script: string;
  clips: ClipItem[];
  settings: ReelSettings;
}

/** Unique, filesystem-safe names – the backend stores clips by filename. */
function safeClipName(index: number, original: string): string {
  const dot = original.lastIndexOf('.');
  const ext = dot > 0 ? original.slice(dot).toLowerCase() : '.mp4';
  const base = (dot > 0 ? original.slice(0, dot) : original).replace(/[^\w-]+/g, '_').slice(0, 40) || 'clip';
  return `${String(index + 1).padStart(2, '0')}-${base}${ext}`;
}

export function createJob(
  { script, clips, settings }: CreateJobInput,
  opts: { onProgress?: (f: number) => void; signal?: AbortSignal } = {},
) {
  const form = new FormData();
  form.append('script', script.trim());
  form.append('tts_provider', settings.ttsProvider);
  form.append('editing_style', settings.editingStyle);
  form.append('intensity', settings.intensity);
  form.append('caption_style', settings.captionStyle);
  form.append('subtitle_position', settings.subtitlePosition);
  clips.forEach((c, i) => form.append('clips', c.file, safeClipName(i, c.name)));
  return postForm<{ job_id: string; status: string; message: string }>('/generate', form, opts);
}

export const getStatus = (jobId: string, signal?: AbortSignal) =>
  request<JobStatus>(`/status/${encodeURIComponent(jobId)}`, { signal });

export const getResult = (jobId: string, signal?: AbortSignal) =>
  request<JobResult>(`/result/${encodeURIComponent(jobId)}`, { signal });

export const deleteJob = (jobId: string) =>
  request<void>(`/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' });

export const cancelJob = (jobId: string) =>
  request<{ message: string }>(`/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });

export const getPlan = (jobId: string, signal?: AbortSignal) =>
  request<EditingPlan>(`/result/${encodeURIComponent(jobId)}/plan`, { signal });

/** Range-capable stream for <video>. */
export const streamUrl = (jobId: string) => withToken(absoluteUrl(`/result/${encodeURIComponent(jobId)}/stream`));
/** Attachment download (browser handles it – nothing buffered in JS). */
export const downloadUrl = (jobId: string) => withToken(absoluteUrl(`/result/${encodeURIComponent(jobId)}/download`));

export interface ServerJob {
  job_id: string;
  status: JobStatus['status'];
  progress: number;
  current_stage: string;
  created_at: string;
  updated_at: string;
  error?: string | null;
  script: string;
  clip_count: number;
  tts_provider: ReelSettings['ttsProvider'];
  editing_style: ReelSettings['editingStyle'];
  intensity: ReelSettings['intensity'];
  caption_style: ReelSettings['captionStyle'];
  subtitle_position: ReelSettings['subtitlePosition'];
}

/** Server-side history (survives clearing the browser, follows the account). */
export const listJobs = (signal?: AbortSignal) => request<{ jobs: ServerJob[] }>('/jobs', { signal });
