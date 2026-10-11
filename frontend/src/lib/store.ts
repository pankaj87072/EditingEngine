import { useSyncExternalStore } from 'react';

/** Tiny localStorage-backed store (no extra deps). */
export function createLocalStore<T>(key: string, initial: T, sanitize?: (raw: unknown) => T) {
  const listeners = new Set<() => void>();
  let cache: T;

  const read = (): T => {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return initial;
      const parsed = JSON.parse(raw);
      return sanitize ? sanitize(parsed) : (parsed as T);
    } catch {
      return initial;
    }
  };
  cache = read();

  const emit = () => listeners.forEach((l) => l());

  window.addEventListener('storage', (e) => {
    if (e.key === key) {
      cache = read();
      emit();
    }
  });

  return {
    get: () => cache,
    set(next: T) {
      cache = next;
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {
        /* storage full or blocked – keep in-memory value */
      }
      emit();
    },
    subscribe(l: () => void) {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    use(): T {
      return useSyncExternalStore(this.subscribe, this.get);
    },
  };
}
