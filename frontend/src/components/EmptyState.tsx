import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

export function EmptyState({ icon: Icon, title, body, action }: { icon: LucideIcon; title: string; body: string; action?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center px-6 py-14 text-center">
      <div className="mb-5 grid h-14 w-14 place-items-center rounded-2xl bg-raised text-violet">
        <Icon size={26} aria-hidden />
      </div>
      <h2 className="text-xl font-semibold">{title}</h2>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-mute">{body}</p>
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}
