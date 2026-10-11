import { getToken, UNAUTHORIZED_EVENT } from './token';

export const API_BASE = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/$/, '');

export type ApiErrorKind = 'network' | 'timeout' | 'http' | 'aborted';

export class ApiError extends Error {
  constructor(
    public kind: ApiErrorKind,
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export const absoluteUrl = (path: string) => (/^https?:\/\//.test(path) ? path : `${API_BASE}${path}`);

/** FastAPI returns {detail: string | [{msg}]} or {error, message}. */
function extractDetail(body: unknown): string {
  if (!body || typeof body !== 'object') return '';
  const b = body as Record<string, unknown>;
  if (typeof b.detail === 'string') return b.detail;
  if (Array.isArray(b.detail)) {
    return b.detail
      .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : ''))
      .filter(Boolean)
      .join('; ');
  }
  if (typeof b.message === 'string') return b.message;
  return '';
}

/** Turn any failure into a sentence a non-technical person can act on. */
export function friendlyMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return 'Something went wrong. Please try again.';
  switch (err.kind) {
    case 'network':
      return "Can't reach the AutoVideoGen server. Check your connection and that the server is running.";
    case 'timeout':
      return 'The server took too long to respond. Please try again.';
    case 'aborted':
      return 'Cancelled.';
  }
  switch (err.status) {
    case 401:
      return 'Please sign in to continue.';
    case 404:
      return 'This Reel could not be found. It may have been deleted from the server.';
    case 409:
      return 'This Reel is not ready yet.';
    case 410:
      return 'The video file is no longer on the server.';
    case 415:
      return 'One of your files is not a supported video. Use MP4, MOV, AVI, MKV or WebM.';
    case 413:
      return 'One of your files is too large for the server.';
    case 422:
      return err.message && err.message.length < 160
        ? err.message
        : 'Some of your input was not accepted. Check your script and clips.';
    case 502:
      return 'The voice service had a problem. Try again, or choose a different voice.';
    default:
      return err.status >= 500
        ? 'The server had a problem while handling this. Please try again in a moment.'
        : 'The request could not be completed. Please try again.';
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** Retries on network errors / 5xx. Only used for idempotent calls. */
  retries?: number;
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, signal, timeoutMs = 15000, retries = method === 'GET' ? 2 : 0 } = opts;
  let attempt = 0;
  for (;;) {
    const ctrl = new AbortController();
    const onAbort = () => ctrl.abort();
    signal?.addEventListener('abort', onAbort);
    const timer = setTimeout(() => ctrl.abort('timeout'), timeoutMs);
    try {
      const headers: Record<string, string> = {};
      const token = getToken();
      if (token) headers.Authorization = `Bearer ${token}`;
      if (body !== undefined) headers['Content-Type'] = 'application/json';
      const res = await fetch(`${API_BASE}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: ctrl.signal,
      });
      if (!res.ok) {
        if (res.status === 401 && token) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
        let body: unknown;
        try {
          body = await res.json();
        } catch {
          /* non-JSON error body */
        }
        throw new ApiError('http', res.status, extractDetail(body));
      }
      return (res.status === 204 ? undefined : await res.json()) as T;
    } catch (e) {
      let err: ApiError;
      if (e instanceof ApiError) err = e;
      else if (signal?.aborted) err = new ApiError('aborted', 0, 'aborted');
      else if (ctrl.signal.aborted) err = new ApiError('timeout', 0, 'timeout');
      else err = new ApiError('network', 0, 'network');

      const retryable = err.kind === 'network' || err.kind === 'timeout' || (err.kind === 'http' && err.status >= 500);
      if (retryable && attempt < retries) {
        attempt += 1;
        await sleep(400 * 2 ** attempt);
        continue;
      }
      throw err;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
    }
  }
}

/** multipart POST with upload progress (fetch can't report upload progress). */
export function postForm<T>(
  path: string,
  form: FormData,
  opts: { onProgress?: (fraction: number) => void; signal?: AbortSignal } = {},
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE}${path}`);
    xhr.responseType = 'json';
    const token = getToken();
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) opts.onProgress?.(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as T);
      else {
        if (xhr.status === 401 && token) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
        reject(new ApiError('http', xhr.status, extractDetail(xhr.response)));
      }
    };
    xhr.onerror = () => reject(new ApiError('network', 0, 'network'));
    xhr.onabort = () => reject(new ApiError('aborted', 0, 'aborted'));
    opts.signal?.addEventListener('abort', () => xhr.abort());
    xhr.send(form);
  });
}
