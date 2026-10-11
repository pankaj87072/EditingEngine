import { Link } from 'react-router-dom';
import { Download, Film, Loader2, Trash2 } from 'lucide-react';
import { StatusBadge } from './StatusBadge';
import { buttonClasses } from './Button';
import { downloadUrl, streamUrl } from '@/api/jobs';
import { useInView } from '@/hooks/useInView';
import { updateProject } from '@/lib/projects';
import { formatDate, formatDuration } from '@/utils/format';
import type { ProjectView } from '@/hooks/useProjects';
import { ProgressBar } from './Progress';
import { useState } from 'react';

interface Props {
  project: ProjectView;
  onDelete: (p: ProjectView) => void;
}

export function ProjectCard({ project: p, onDelete }: Props) {
  const [ref, seen] = useInView<HTMLAnchorElement>();
  const [thumbFailed, setThumbFailed] = useState(false);
  const state = p.status?.status;
  const completed = state === 'completed';
  const active = state === 'pending' || state === 'processing';

  return (
    <article className="card group flex flex-col overflow-hidden transition-colors hover:border-mute/40">
      <Link
        ref={ref}
        to={`/reels/${p.jobId}`}
        aria-label={`Open ${p.title}`}
        className="relative block aspect-[4/5] overflow-hidden bg-raised"
      >
        {completed && seen && !thumbFailed ? (
          <video
            src={`${streamUrl(p.jobId)}#t=0.5`}
            preload="metadata"
            muted
            playsInline
            tabIndex={-1}
            aria-hidden
            className="h-full w-full object-cover"
            onLoadedMetadata={(e) => {
              const d = e.currentTarget.duration;
              if (isFinite(d) && p.durationSec == null) updateProject(p.jobId, { durationSec: d });
            }}
            onError={() => setThumbFailed(true)}
          />
        ) : (
          <div className="grid h-full place-items-center text-mute">
            {active ? <Loader2 size={28} className="animate-spin text-azure" aria-hidden /> : <Film size={28} aria-hidden />}
          </div>
        )}
        {p.durationSec != null && completed && (
          <span className="absolute bottom-2 right-2 rounded-md bg-black/70 px-1.5 py-0.5 text-xs tabular-nums">
            {formatDuration(p.durationSec)}
          </span>
        )}
      </Link>

      <div className="flex flex-1 flex-col gap-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <h3 className="line-clamp-2 text-base font-semibold leading-snug">{p.title}</h3>
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <StatusBadge project={p} />
          <time className="text-xs text-mute" dateTime={p.createdAt}>
            {formatDate(p.createdAt)}
          </time>
        </div>

        {active && (
          <div className="space-y-1">
            <ProgressBar value={p.status?.progress ?? 0} label={`${p.title} progress`} />
            <p className="text-xs text-mute">{p.status?.current_stage || 'Waiting to start'}</p>
          </div>
        )}

        <div className="mt-auto flex items-center gap-2 pt-1">
          <Link to={`/reels/${p.jobId}`} className={buttonClasses('secondary', 'sm', 'flex-1')}>
            {active ? 'View progress' : 'Open'}
          </Link>
          {completed && (
            <a href={downloadUrl(p.jobId)} download aria-label={`Download ${p.title}`} className={buttonClasses('secondary', 'sm', 'px-3')}>
              <Download size={16} />
            </a>
          )}
          <button
            type="button"
            onClick={() => onDelete(p)}
            aria-label={`Delete ${p.title}`}
            className={buttonClasses('ghost', 'sm', 'px-3 hover:text-bad')}
          >
            <Trash2 size={16} />
          </button>
        </div>
      </div>
    </article>
  );
}
