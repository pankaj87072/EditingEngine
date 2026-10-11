import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { CloudOff } from 'lucide-react';
import { StageTrack } from '@/components/Progress';
import { Button, buttonClasses } from '@/components/Button';
import { Modal } from '@/components/Modal';
import { cancelJob } from '@/api/jobs';
import { ApiError, friendlyMessage } from '@/api/client';
import { formatElapsed, parseServerDate } from '@/utils/format';
import type { JobStatus } from '@/types';

/** Labels shown to the user. Thresholds match the backend's real progress checkpoints. */
export const STAGES = [
  { label: 'Preparing project', hint: 'Your files are saved and the job is queued.' },
  { label: 'Analyzing clips', hint: 'Measuring quality, motion, cuts and where the subject is in each clip.' },
  { label: 'Understanding script', hint: 'Finding the hook, key words and the pace of each scene.' },
  { label: 'Matching clips', hint: 'Choosing the best part of the best clip for every shot.' },
  { label: 'Generating voice', hint: 'Creating the voiceover.' },
  { label: 'Creating subtitles', hint: 'Timing captions to the voiceover.' },
  { label: 'Editing video', hint: 'Cropping, motion, cuts and export. This is the longest step.' },
  { label: 'Finalizing Reel', hint: 'Checking the finished video.' },
];

export function stageIndex(job: Pick<JobStatus, 'status' | 'progress'>): number {
  if (job.status === 'completed') return 7;
  if (job.status === 'pending') return 0;
  const p = job.progress;
  // Thresholds match the backend's real progress checkpoints (8, 20, 28, 42, 62, 75, 94).
  return p >= 94 ? 7 : p >= 75 ? 6 : p >= 62 ? 5 : p >= 42 ? 4 : p >= 28 ? 3 : p >= 20 ? 2 : p >= 8 ? 1 : 0;
}

export function ProcessingView({ job, title, startedAt, reconnecting }: { job: JobStatus; title: string; startedAt?: string; reconnecting: boolean }) {
  const qc = useQueryClient();
  const [now, setNow] = useState(Date.now());
  const [askCancel, setAskCancel] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  const doCancel = async () => {
    setCancelling(true);
    setCancelError(null);
    try {
      await cancelJob(job.job_id);
      setAskCancel(false);
      void qc.invalidateQueries({ queryKey: ['job', job.job_id] });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // Already finished or stopped – just refresh the status.
        setAskCancel(false);
        void qc.invalidateQueries({ queryKey: ['job', job.job_id] });
      } else setCancelError(friendlyMessage(e));
    } finally {
      setCancelling(false);
    }
  };
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const idx = stageIndex(job);
  const start = (startedAt ? new Date(startedAt) : parseServerDate(job.created_at)).getTime();
  const elapsed = now - start;
  const stage = STAGES[idx];

  return (
    <div className="mx-auto max-w-2xl py-6 sm:py-14">
      <p className="text-sm text-mute">Creating</p>
      <h1 className="mt-1 line-clamp-2 text-2xl font-bold sm:text-3xl">{title}</h1>

      <div className="card mt-8 p-6 sm:p-8" aria-live="polite">
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="text-sm text-mute">{job.status === 'pending' ? 'Waiting to start' : 'Now'}</p>
            <p className="mt-1 font-display text-2xl font-bold">{stage.label}</p>
          </div>
          <p className="font-display text-5xl font-bold tabular-nums" aria-label={`${job.progress} percent`}>
            {job.progress}
            <span className="text-2xl text-mute">%</span>
          </p>
        </div>

        <div className="mt-6">
          <StageTrack stages={STAGES.map((s) => s.label)} active={idx} finished={false} />
        </div>
        <p className="mt-4 text-sm leading-relaxed text-mute">{stage.hint}</p>

        <ul className="mt-6 grid gap-1.5 text-sm sm:grid-cols-2">
          {STAGES.slice(0, 7).map((s, i) => (
            <li key={s.label} className={i < idx ? 'text-ink' : i === idx ? 'font-medium text-ink' : 'text-mute/60'}>
              <span className="mr-2 inline-block w-3 text-ok">{i < idx ? '✓' : ''}</span>
              {s.label}
            </li>
          ))}
        </ul>

        <div className="mt-6 flex items-center justify-between border-t border-line pt-4 text-xs text-mute">
          <span>Elapsed {formatElapsed(elapsed)}</span>
          {job.progress >= 75 && job.progress < 94 && <span>Progress holds at 75% while the video renders</span>}
        </div>
      </div>

      {reconnecting && (
        <p role="status" className="mt-4 flex items-center gap-2 rounded-xl border border-warn/30 bg-warn/10 p-3 text-sm text-warn">
          <CloudOff size={16} aria-hidden /> Lost contact with the server. Retrying. Your Reel is still being made.
        </p>
      )}
      {elapsed > 15 * 60_000 && (
        <p role="status" className="mt-4 rounded-xl border border-warn/30 bg-warn/10 p-3 text-sm text-warn">
          This is taking longer than usual. Long scripts and large clips need more time.
        </p>
      )}

      <p className="mt-6 text-sm text-mute">
        You can close this page. The Reel keeps rendering and will be in your{' '}
        <Link to="/app" className="text-azure hover:underline">dashboard</Link>.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        <Link to="/app" className={buttonClasses('secondary', 'md')}>Go to dashboard</Link>
        <Button variant="ghost" onClick={() => setAskCancel(true)} disabled={cancelling}>
          {cancelling ? 'Stopping…' : 'Cancel this Reel'}
        </Button>
      </div>
      {cancelling && (
        <p role="status" className="mt-3 text-sm text-mute">Stopping after the current step finishes…</p>
      )}

      <Modal
        open={askCancel}
        onClose={() => !cancelling && setAskCancel(false)}
        title="Cancel this Reel?"
        footer={
          <>
            <Button variant="ghost" onClick={() => setAskCancel(false)} disabled={cancelling}>Keep going</Button>
            <Button variant="danger" onClick={doCancel} disabled={cancelling}>{cancelling ? 'Stopping…' : 'Cancel Reel'}</Button>
          </>
        }
      >
        Editing stops after the current step. Your uploaded clips are discarded, but your script and style are kept so you can try again.
        {cancelError && <span role="alert" className="mt-3 block text-bad">{cancelError}</span>}
      </Modal>
    </div>
  );
}
