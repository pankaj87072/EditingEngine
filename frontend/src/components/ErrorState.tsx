import { AlertTriangle } from 'lucide-react';
import type { ReactNode } from 'react';
import { Button } from './Button';

interface Props {
  title: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
  children?: ReactNode;
  reference?: string;
  compact?: boolean;
}

export function ErrorState({ title, message, onRetry, retryLabel = 'Try again', children, reference, compact }: Props) {
  return (
    <div role="alert" className={`card border-bad/30 ${compact ? 'p-4' : 'px-6 py-10 text-center'}`}>
      <div className={compact ? 'flex gap-3' : 'flex flex-col items-center'}>
        <div className={`grid shrink-0 place-items-center rounded-xl bg-bad/10 text-bad ${compact ? 'h-9 w-9' : 'mb-4 h-12 w-12'}`}>
          <AlertTriangle size={compact ? 18 : 22} aria-hidden />
        </div>
        <div className={compact ? '' : 'max-w-md'}>
          <h2 className="text-base font-semibold">{title}</h2>
          <p className="mt-1 text-sm leading-relaxed text-mute">{message}</p>
          {reference && <p className="mt-2 text-xs text-mute/70">Reference: {reference}</p>}
          {(onRetry || children) && (
            <div className={`mt-4 flex flex-wrap gap-2 ${compact ? '' : 'justify-center'}`}>
              {onRetry && <Button onClick={onRetry} variant="secondary" size="sm">{retryLabel}</Button>}
              {children}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
