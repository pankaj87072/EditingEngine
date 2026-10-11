import { AlertCircle, CheckCircle2, Clock3, Loader2, CircleSlash } from 'lucide-react';
import { cn } from '@/lib/cn';
import type { ProjectView } from '@/hooks/useProjects';

export function statusInfo(p: Pick<ProjectView, 'status' | 'load'>) {
  if (p.load === 'missing') return { key: 'missing', label: 'Removed from server', tone: 'text-mute bg-raised', Icon: CircleSlash };
  switch (p.status?.status) {
    case 'completed':
      return { key: 'done', label: 'Ready', tone: 'text-ok bg-ok/10', Icon: CheckCircle2 };
    case 'processing':
      return { key: 'busy', label: 'Editing', tone: 'text-azure bg-azure/10', Icon: Loader2 };
    case 'pending':
      return { key: 'queued', label: 'Queued', tone: 'text-mute bg-raised', Icon: Clock3 };
    case 'cancelled':
      return { key: 'cancelled', label: 'Cancelled', tone: 'text-mute bg-raised', Icon: CircleSlash };
    case 'failed':
      return { key: 'failed', label: 'Failed', tone: 'text-bad bg-bad/10', Icon: AlertCircle };
    default:
      return { key: 'unknown', label: p.load === 'error' ? 'Unavailable' : 'Checking…', tone: 'text-mute bg-raised', Icon: Clock3 };
  }
}

export function StatusBadge({ project }: { project: Pick<ProjectView, 'status' | 'load'> }) {
  const { label, tone, Icon, key } = statusInfo(project);
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium', tone)}>
      <Icon size={13} className={key === 'busy' ? 'animate-spin' : undefined} aria-hidden />
      {label}
    </span>
  );
}
