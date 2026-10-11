import { cn } from '@/lib/cn';
import type { ReactNode } from 'react';

interface Props<T extends string> {
  name: string;
  legend: string;
  help?: string;
  value: T;
  options: { value: T; label: string; hint: string }[];
  onChange: (v: T) => void;
  columns?: string;
  render?: (o: { value: T; label: string; hint: string }) => ReactNode;
}

/** Accessible radio group rendered as selectable cards. */
export function RadioCards<T extends string>({ name, legend, help, value, options, onChange, columns = 'sm:grid-cols-2', render }: Props<T>) {
  return (
    <fieldset>
      <legend className="text-base font-semibold">{legend}</legend>
      {help && <p className="mt-0.5 text-sm text-mute">{help}</p>}
      <div className={cn('mt-3 grid gap-2.5', columns)}>
        {options.map((o) => (
          <label key={o.value} className="relative block cursor-pointer">
            <input
              type="radio"
              name={name}
              value={o.value}
              checked={value === o.value}
              onChange={() => onChange(o.value)}
              className="peer sr-only"
            />
            <div className="h-full rounded-xl border border-line bg-surface p-3.5 transition-colors hover:border-mute/60 peer-checked:border-violet peer-checked:bg-violet/10 peer-focus-visible:ring-2 peer-focus-visible:ring-azure">
              {render ? (
                render(o)
              ) : (
                <>
                  <span className="block text-sm font-medium">{o.label}</span>
                  <span className="mt-0.5 block text-xs leading-snug text-mute">{o.hint}</span>
                </>
              )}
            </div>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
