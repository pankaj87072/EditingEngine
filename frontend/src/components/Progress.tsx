import { cn } from '@/lib/cn';

export function ProgressBar({ value, label }: { value: number; label: string }) {
  const v = Math.max(0, Math.min(100, value));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(v)}
      className="h-2 w-full overflow-hidden rounded-full bg-raised"
    >
      <div className="brand-gradient h-full rounded-full transition-[width] duration-500" style={{ width: `${v}%` }} />
    </div>
  );
}

/**
 * Segmented track – one block per pipeline stage, like cuts on a timeline.
 * Fill reflects real backend stage; the active block shimmers (not a fake %).
 */
export function StageTrack({ stages, active, finished }: { stages: string[]; active: number; finished: boolean }) {
  return (
    <ol className="flex gap-1.5" aria-label="Pipeline stages">
      {stages.map((s, i) => {
        const done = finished || i < active;
        const current = !finished && i === active;
        return (
          <li
            key={s}
            aria-current={current ? 'step' : undefined}
            className={cn(
              'relative h-2.5 flex-1 overflow-hidden rounded-full',
              done ? 'brand-gradient' : 'bg-raised',
            )}
            title={s}
          >
            {current && (
              <span className="absolute inset-0 bg-gradient-to-r from-transparent via-violet/70 to-transparent animate-sheen" />
            )}
            <span className="sr-only">
              {s}: {done ? 'done' : current ? 'in progress' : 'waiting'}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
