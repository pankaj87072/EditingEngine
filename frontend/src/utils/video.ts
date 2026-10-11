import type { ClipItem } from '@/types';

export const ACCEPTED_EXT = ['.mp4', '.mov', '.avi', '.mkv', '.webm'];
export const MAX_FILE_BYTES = 500 * 1024 * 1024; // client-side guard; backend sets no limit

export type FileCheck = { ok: true } | { ok: false; reason: string };

export function checkVideoFile(file: File): FileCheck {
  const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
  if (!ACCEPTED_EXT.includes(ext))
    return { ok: false, reason: `“${file.name}” isn't a supported video. Use MP4, MOV, AVI, MKV or WebM.` };
  if (file.size === 0) return { ok: false, reason: `“${file.name}” is empty.` };
  if (file.size > MAX_FILE_BYTES) return { ok: false, reason: `“${file.name}” is larger than 500 MB.` };
  return { ok: true };
}

type Probe = Pick<ClipItem, 'duration' | 'width' | 'height' | 'thumb'>;

/**
 * Reads duration/size and grabs one small JPEG frame using a throw-away
 * <video>. The file is streamed by the browser – never loaded into JS memory.
 * Resolves to null for formats the browser can't decode (e.g. some MKV/AVI).
 */
export function probeVideo(file: File, timeoutMs = 8000): Promise<Probe | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const v = document.createElement('video');
    v.preload = 'metadata';
    v.muted = true;
    v.playsInline = true;

    let done = false;
    const finish = (r: Probe | null) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      v.removeAttribute('src');
      v.load();
      URL.revokeObjectURL(url);
      resolve(r);
    };
    const timer = setTimeout(() => finish(null), timeoutMs);

    v.onerror = () => finish(null);
    v.onloadedmetadata = () => {
      const duration = isFinite(v.duration) ? v.duration : undefined;
      const base = { duration, width: v.videoWidth, height: v.videoHeight };
      v.currentTime = Math.min(0.5, (duration ?? 1) / 2);
      v.onseeked = () => {
        try {
          const w = 180;
          const h = Math.round((w * v.videoHeight) / v.videoWidth) || 320;
          const c = document.createElement('canvas');
          c.width = w;
          c.height = h;
          c.getContext('2d')?.drawImage(v, 0, 0, w, h);
          finish({ ...base, thumb: c.toDataURL('image/jpeg', 0.7) });
        } catch {
          finish(base);
        }
      };
    };
    v.src = url;
  });
}

export const isLandscape = (c: Pick<ClipItem, 'width' | 'height'>) => !!c.width && !!c.height && c.width > c.height;
