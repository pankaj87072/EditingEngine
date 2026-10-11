import { useState } from 'react';
import { Link } from 'react-router-dom';
import { History as HistoryIcon } from 'lucide-react';
import { buttonClasses } from '@/components/Button';
import { EmptyState } from '@/components/EmptyState';
import { ProjectCard } from '@/components/ProjectCard';
import { DeleteDialog } from '@/components/DeleteDialog';
import { ServerNotice } from '@/components/ServerNotice';
import { useProjects, type ProjectView } from '@/hooks/useProjects';
import { cn } from '@/lib/cn';

const FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'completed', label: 'Ready' },
  { id: 'active', label: 'In progress' },
  { id: 'failed', label: 'Failed or cancelled' },
] as const;
type Filter = (typeof FILTERS)[number]['id'];

const matches = (p: ProjectView, f: Filter) => {
  const s = p.status?.status;
  if (f === 'all') return true;
  if (f === 'completed') return s === 'completed';
  if (f === 'failed') return s === 'failed' || s === 'cancelled';
  return s === 'pending' || s === 'processing';
};

export default function History() {
  const { projects, total, loadingServer } = useProjects();
  const [filter, setFilter] = useState<Filter>('all');
  const [target, setTarget] = useState<ProjectView | null>(null);
  const shown = projects.filter((p) => matches(p, filter));

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold">History</h1>
        <p className="mt-1 text-mute">Every Reel you’ve generated in this browser.</p>
      </div>
      <ServerNotice />

      {total === 0 && loadingServer ? (
        <div className="grid h-40 place-items-center" role="status" aria-label="Loading your Reels">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-line border-t-violet" />
        </div>
      ) : total === 0 ? (
        <EmptyState
          icon={HistoryIcon}
          title="No Reels yet"
          body="Reels you generate will show up here so you can reopen, download or delete them."
          action={<Link to="/app/new" className={buttonClasses('primary', 'md')}>Create a Reel</Link>}
        />
      ) : (
        <>
          <div role="group" aria-label="Filter by status" className="flex flex-wrap gap-2">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                aria-pressed={filter === f.id}
                onClick={() => setFilter(f.id)}
                className={cn(
                  'h-10 rounded-full border px-4 text-sm font-medium transition-colors',
                  filter === f.id ? 'border-violet bg-violet/15 text-ink' : 'border-line text-mute hover:text-ink',
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
          {shown.length === 0 ? (
            <p className="text-sm text-mute">No Reels match this filter.</p>
          ) : (
            <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
              {shown.map((p) => (
                <ProjectCard key={p.jobId} project={p} onDelete={setTarget} />
              ))}
            </div>
          )}
        </>
      )}
      <DeleteDialog target={target} onClose={() => setTarget(null)} />
    </div>
  );
}
