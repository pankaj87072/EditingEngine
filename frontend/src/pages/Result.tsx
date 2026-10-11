import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Download, Pencil, Plus, Trash2 } from 'lucide-react';
import { Button, buttonClasses } from '@/components/Button';
import { VideoPreview } from '@/components/VideoPreview';
import { ErrorState } from '@/components/ErrorState';
import { DeleteDialog } from '@/components/DeleteDialog';
import { EditingPlanPanel } from '@/components/EditingPlanPanel';
import { QualityPanel } from '@/components/QualityPanel';
import { absoluteUrl, friendlyMessage } from '@/api/client';
import { downloadUrl, streamUrl } from '@/api/jobs';
import { withToken } from '@/api/token';
import { useJobResult } from '@/hooks/useJob';
import { useDraft } from '@/lib/draft';
import { updateProject } from '@/lib/projects';
import { CAPTION_STYLES, EDITING_STYLES, INTENSITIES, labelOf, POSITIONS, VOICES } from '@/lib/options';
import { formatDate, formatDuration } from '@/utils/format';
import type { JobStatus, ProjectRecord } from '@/types';

export function ResultView({ job, project }: { job: JobStatus; project?: ProjectRecord }) {
  const nav = useNavigate();
  const { reset, load } = useDraft();
  const result = useJobResult(job.job_id, true);
  const [videoFailed, setVideoFailed] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const title = project?.title ?? 'Your Reel';
  const s = project?.settings;

  const outputMissing = result.isSuccess && !result.data.output_url;
  const unavailable = videoFailed || outputMissing;

  const another = () => {
    reset();
    nav('/app/new');
  };
  const editSettings = () => {
    if (!project) return;
    load(project.script, project.settings);
    nav('/app/new?from=edit');
  };

  return (
    <div className="grid gap-10 py-2 lg:grid-cols-[minmax(0,26rem)_1fr] lg:items-start lg:gap-14">
      <div>
        {unavailable ? (
          <ErrorState
            title="This video isn’t available"
            message="The file is no longer on the server. It may have been removed. You can create the Reel again."
          >
            <Button size="sm" onClick={another}>Create another Reel</Button>
          </ErrorState>
        ) : result.isError ? (
          <ErrorState title="Couldn’t load your video" message={friendlyMessage(result.error)} onRetry={() => void result.refetch()} />
        ) : (
          <VideoPreview
            src={streamUrl(job.job_id)}
            onError={() => setVideoFailed(true)}
            onDuration={(d) => isFinite(d) && project && project.durationSec !== d && updateProject(job.job_id, { durationSec: d })}
          />
        )}
      </div>

      <div className="space-y-8">
        <div>
          <p className="text-sm font-medium text-ok">Your Reel is ready</p>
          <h1 className="mt-1 text-3xl font-bold leading-tight">{title}</h1>
        </div>

        <div className="flex flex-wrap gap-3">
          {!unavailable && (
            <a
              href={result.data?.output_url ? withToken(absoluteUrl(result.data.output_url)) : downloadUrl(job.job_id)}
              download
              className={buttonClasses('primary', 'lg', 'flex-1 sm:flex-none')}
            >
              <Download size={18} aria-hidden /> Download MP4
            </a>
          )}
          <Button variant="secondary" size="lg" onClick={another}>
            <Plus size={18} aria-hidden /> Create another Reel
          </Button>
          {project && (
            <Button variant="secondary" size="lg" onClick={editSettings}>
              <Pencil size={16} aria-hidden /> Edit settings
            </Button>
          )}
          <Button variant="ghost" size="lg" className="hover:text-bad" onClick={() => setConfirmDelete(true)}>
            <Trash2 size={16} aria-hidden /> Delete
          </Button>
        </div>

        <dl className="card divide-y divide-line text-sm">
          <Info label="Created" value={formatDate(project?.createdAt ?? job.created_at)} />
          <Info label="Length" value={formatDuration(project?.durationSec)} />
          <Info label="Format" value="1080×1920 vertical MP4" />
          {project && <Info label="Clips used" value={String(project.clipCount)} />}
          {s && (
            <>
              <Info label="Voice" value={labelOf(VOICES, s.ttsProvider)} />
              <Info label="Editing style" value={labelOf(EDITING_STYLES, s.editingStyle)} />
              <Info label="Intensity" value={labelOf(INTENSITIES, s.intensity)} />
              <Info label="Captions" value={`${labelOf(CAPTION_STYLES, s.captionStyle)}, ${labelOf(POSITIONS, s.subtitlePosition).toLowerCase()}`} />
            </>
          )}
        </dl>

        <QualityPanel report={result.data?.report} />

        <EditingPlanPanel jobId={job.job_id} />

        {project?.script && (
          <details className="card group px-4 py-3 text-sm">
            <summary className="cursor-pointer font-medium">Script</summary>
            <p className="mt-3 whitespace-pre-wrap leading-relaxed text-mute">{project.script}</p>
          </details>
        )}
        <Link to="/app" className="inline-block text-sm text-mute hover:text-ink">Back to dashboard</Link>
      </div>

      <DeleteDialog
        target={confirmDelete ? { jobId: job.job_id, title } : null}
        onClose={() => setConfirmDelete(false)}
        onDeleted={() => nav('/app')}
      />
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 px-4 py-3">
      <dt className="text-mute">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  );
}
