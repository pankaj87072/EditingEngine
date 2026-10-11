import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button, buttonClasses } from '@/components/Button';
import { ErrorState } from '@/components/ErrorState';
import { ApiError, friendlyMessage } from '@/api/client';
import { useJob } from '@/hooks/useJob';
import { getProjectRecord, removeProject, useProjectRecords } from '@/lib/projects';
import { explainJobFailure } from '@/utils/errors';
import { ProcessingView } from './Processing';
import { ResultView } from './Result';
import { useDraft } from '@/lib/draft';

export default function ReelPage() {
  const { jobId } = useParams();
  const nav = useNavigate();
  const { load } = useDraft();
  useProjectRecords(); // re-render when the local record changes (duration, etc.)
  const job = useJob(jobId);
  const project = jobId ? getProjectRecord(jobId) : undefined;

  if (job.isPending && !job.isError) {
    return (
      <div className="grid min-h-[50vh] place-items-center" role="status" aria-label="Loading Reel">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-line border-t-violet" />
      </div>
    );
  }

  if (job.isError && !job.data) {
    const gone = job.error instanceof ApiError && job.error.status === 404;
    return (
      <div className="mx-auto max-w-lg py-10">
        <ErrorState
          title={gone ? 'This Reel is no longer on the server' : 'Couldn’t load this Reel'}
          message={friendlyMessage(job.error)}
          onRetry={gone ? undefined : () => void job.refetch()}
        >
          {gone && project && (
            <Button size="sm" variant="secondary" onClick={() => (removeProject(project.jobId), nav('/app'))}>
              Remove from my list
            </Button>
          )}
          <Link to="/app" className={buttonClasses('ghost', 'sm')}>Back to dashboard</Link>
        </ErrorState>
      </div>
    );
  }

  const data = job.data!;

  if (data.status === 'completed') return <ResultView job={data} project={project} />;

  if (data.status === 'cancelled') {
    return (
      <div className="mx-auto max-w-lg py-10">
        <ErrorState title="This Reel was cancelled" message="Nothing was saved except your script and style. You can start again whenever you like.">
          {project && (
            <Button
              size="sm"
              onClick={() => {
                load(project.script, project.settings);
                nav('/app/new?from=edit');
              }}
            >
              Start again with this script
            </Button>
          )}
          <Link to="/app" className={buttonClasses('ghost', 'sm')}>Back to dashboard</Link>
        </ErrorState>
      </div>
    );
  }

  if (data.status === 'failed') {
    const why = explainJobFailure(data.error);
    return (
      <div className="mx-auto max-w-lg py-10">
        <ErrorState title={why.title} message={why.body} reference={data.job_id.slice(0, 8)}>
          {project && (
            <Button
              size="sm"
              onClick={() => {
                load(project.script, project.settings);
                nav('/app/new?from=edit');
              }}
            >
              Try again with the same script
            </Button>
          )}
          <Link to="/app" className={buttonClasses('ghost', 'sm')}>Back to dashboard</Link>
        </ErrorState>
      </div>
    );
  }

  return (
    <ProcessingView
      job={data}
      title={project?.title ?? 'Your Reel'}
      startedAt={project?.createdAt}
      reconnecting={job.isRefetchError || job.failureCount > 0}
    />
  );
}
