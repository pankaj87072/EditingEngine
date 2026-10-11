import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Modal } from './Modal';
import { Button } from './Button';
import { deleteJob } from '@/api/jobs';
import { ApiError, friendlyMessage } from '@/api/client';
import { removeProject } from '@/lib/projects';

interface Props {
  target: { jobId: string; title: string } | null;
  onClose: () => void;
  onDeleted?: () => void;
}

export function DeleteDialog({ target, onClose, onDeleted }: Props) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const finish = () => {
    if (!target) return;
    removeProject(target.jobId);
    qc.removeQueries({ queryKey: ['job', target.jobId] });
    qc.removeQueries({ queryKey: ['result', target.jobId] });
    setError(null);
    onClose();
    onDeleted?.();
  };

  const confirm = async () => {
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      await deleteJob(target.jobId);
      finish();
    } catch (e) {
      // 404 = already gone on the server, which is what we wanted.
      if (e instanceof ApiError && e.status === 404) finish();
      else if (e instanceof ApiError && e.status === 409) setError('This Reel is still being edited. Wait for it to finish, then delete it.');
      else setError(friendlyMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={!!target}
      onClose={() => !busy && (setError(null), onClose())}
      title="Delete this Reel?"
      footer={
        <>
          <Button variant="ghost" onClick={() => (setError(null), onClose())} disabled={busy}>
            Cancel
          </Button>
          {error && (
            <Button variant="secondary" onClick={finish} disabled={busy}>
              Remove from my list only
            </Button>
          )}
          <Button variant="danger" onClick={confirm} disabled={busy}>
            {busy ? 'Deleting…' : 'Delete Reel'}
          </Button>
        </>
      }
    >
      <p>
        “{target?.title}” and its video file will be permanently deleted from the server. This can’t be undone.
      </p>
      {error && <p role="alert" className="mt-3 text-bad">{error}</p>}
    </Modal>
  );
}
