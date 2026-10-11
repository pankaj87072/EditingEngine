import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { ClipItem, ReelSettings } from '@/types';
import { getPrefs } from './projects';
import { checkVideoFile, probeVideo } from '@/utils/video';
import { MAX_CLIPS } from '@/utils/script';

/**
 * The in-progress Reel. Script + style persist across reloads; clips can't
 * (File handles don't survive a reload) so they live in memory only.
 */
interface DraftCtx {
  script: string;
  setScript: (s: string) => void;
  settings: ReelSettings;
  setSettings: (s: ReelSettings) => void;
  clips: ClipItem[];
  addFiles: (files: File[]) => string[]; // returns user-facing problems
  removeClip: (id: string) => void;
  moveClip: (from: number, to: number) => void;
  reset: () => void;
  load: (script: string, settings: ReelSettings) => void;
}

const Ctx = createContext<DraftCtx | null>(null);
const KEY = 'avg.draft.v1';

function readDraft(): { script: string; settings: ReelSettings } {
  try {
    const d = JSON.parse(localStorage.getItem(KEY) ?? '');
    if (d && typeof d.script === 'string') return { script: d.script, settings: { ...getPrefs(), ...d.settings } };
  } catch {
    /* ignore */
  }
  return { script: '', settings: getPrefs() };
}

export function DraftProvider({ children }: { children: ReactNode }) {
  const initial = useRef(readDraft());
  const [script, setScript] = useState(initial.current.script);
  const [settings, setSettings] = useState(initial.current.settings);
  const [clips, setClips] = useState<ClipItem[]>([]);

  useEffect(() => {
    const t = setTimeout(() => {
      try {
        localStorage.setItem(KEY, JSON.stringify({ script, settings }));
      } catch {
        /* ignore */
      }
    }, 400);
    return () => clearTimeout(t);
  }, [script, settings]);

  const addFiles = useCallback(
    (files: File[]) => {
      const problems: string[] = [];
      const accepted: ClipItem[] = [];
      const existing = new Set(clips.map((c) => `${c.name}:${c.size}`));
      for (const f of files) {
        if (clips.length + accepted.length >= MAX_CLIPS) {
          problems.push(`You can add up to ${MAX_CLIPS} clips. Extra files were skipped.`);
          break;
        }
        const check = checkVideoFile(f);
        if (!check.ok) {
          problems.push(check.reason);
          continue;
        }
        const sig = `${f.name}:${f.size}`;
        if (existing.has(sig)) {
          problems.push(`“${f.name}” is already added.`);
          continue;
        }
        existing.add(sig);
        accepted.push({ id: crypto.randomUUID(), file: f, name: f.name, size: f.size, state: 'reading' });
      }
      if (accepted.length) {
        setClips((c) => [...c, ...accepted]);
        // Probe sequentially to keep the main thread responsive.
        void (async () => {
          for (const item of accepted) {
            const info = await probeVideo(item.file);
            setClips((c) =>
              c.map((x) => (x.id === item.id ? { ...x, ...(info ?? {}), state: info ? 'ready' : 'unreadable' } : x)),
            );
          }
        })();
      }
      return problems;
    },
    [clips],
  );

  const value = useMemo<DraftCtx>(
    () => ({
      script,
      setScript,
      settings,
      setSettings,
      clips,
      addFiles,
      removeClip: (id) => setClips((c) => c.filter((x) => x.id !== id)),
      moveClip: (from, to) =>
        setClips((c) => {
          if (to < 0 || to >= c.length) return c;
          const next = c.slice();
          const [m] = next.splice(from, 1);
          next.splice(to, 0, m);
          return next;
        }),
      reset: () => {
        setScript('');
        setSettings(getPrefs());
        setClips([]);
      },
      load: (s, st) => {
        setScript(s);
        setSettings(st);
        setClips([]);
      },
    }),
    [script, settings, clips, addFiles],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useDraft() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useDraft must be used inside DraftProvider');
  return v;
}
