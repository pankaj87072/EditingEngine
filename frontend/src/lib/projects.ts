import type { ProjectRecord, ReelSettings } from '@/types';
import { createLocalStore } from './store';
import { DEFAULT_SETTINGS } from './options';

const MAX_PROJECTS = 100;

const store = createLocalStore<ProjectRecord[]>('avg.projects.v1', [], (raw) =>
  Array.isArray(raw)
    ? raw
        .filter((p) => p && typeof p.jobId === 'string')
        .map((p) => ({ ...p, settings: { ...DEFAULT_SETTINGS, ...(p.settings ?? {}) } }))
    : [],
);

export const useProjectRecords = () => store.use();
export const getProjectRecords = () => store.get();
export const getProjectRecord = (id: string) => store.get().find((p) => p.jobId === id);

export function addProject(p: ProjectRecord) {
  store.set([p, ...store.get().filter((x) => x.jobId !== p.jobId)].slice(0, MAX_PROJECTS));
}

export function updateProject(id: string, patch: Partial<ProjectRecord>) {
  const list = store.get();
  if (!list.some((p) => p.jobId === id)) return;
  store.set(list.map((p) => (p.jobId === id ? { ...p, ...patch } : p)));
}

export function removeProject(id: string) {
  store.set(store.get().filter((p) => p.jobId !== id));
}

export function clearProjects() {
  store.set([]);
}

// ── Default style preferences (Settings page) ────────────────────────────────
const prefs = createLocalStore<ReelSettings>('avg.prefs.v1', DEFAULT_SETTINGS, (raw) => ({
  ...DEFAULT_SETTINGS,
  ...(raw as Partial<ReelSettings>),
}));
export const usePrefs = () => prefs.use();
export const getPrefs = () => prefs.get();
export const setPrefs = (p: ReelSettings) => prefs.set(p);
