import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Clapperboard, Plus } from 'lucide-react';
import { buttonClasses } from '@/components/Button';
import { EmptyState } from '@/components/EmptyState';
import { ProjectCard } from '@/components/ProjectCard';
import { DeleteDialog } from '@/components/DeleteDialog';
import { ServerNotice } from '@/components/ServerNotice';
import { useProjects, type ProjectView } from '@/hooks/useProjects';

export default function Dashboard() {
  const { projects, total, loadingServer } = useProjects(6);
  const [target, setTarget] = useState<ProjectView | null>(null);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">Your Reels</h1>
          <p className="mt-1 text-mute">Recent projects and their status.</p>
        </div>
        <Link to="/app/new" className={buttonClasses('primary', 'md', 'hidden sm:inline-flex')}>
          <Plus size={18} aria-hidden /> New Reel
        </Link>
      </div>

      <ServerNotice />

      {total === 0 && loadingServer ? (
        <div className="grid h-40 place-items-center" role="status" aria-label="Loading your Reels">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-line border-t-violet" />
        </div>
      ) : total === 0 ? (
        <EmptyState
          icon={Clapperboard}
          title="Make your first Reel"
          body="Paste a script, add a few raw clips, and AutoVideoGen edits them into a vertical video. It takes about two minutes of your time."
          action={<Link to="/app/new" className={buttonClasses('primary', 'lg')}>Create a Reel</Link>}
        />
      ) : (
        <>
          <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
            {projects.map((p) => (
              <ProjectCard key={p.jobId} project={p} onDelete={setTarget} />
            ))}
          </div>
          {total > 6 && (
            <Link to="/app/history" className={buttonClasses('secondary', 'md')}>
              View all {total} Reels
            </Link>
          )}
        </>
      )}

      <DeleteDialog target={target} onClose={() => setTarget(null)} />
    </div>
  );
}
