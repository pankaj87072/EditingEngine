import { useState } from 'react';
import { Check, X } from 'lucide-react';
import { Button } from '@/components/Button';
import { Modal } from '@/components/Modal';
import { VideoSettings } from '@/components/VideoSettings';
import { API_BASE } from '@/api/client';
import { useHealth } from '@/hooks/useHealth';
import { clearProjects, setPrefs, usePrefs, useProjectRecords } from '@/lib/projects';
import { useAuth } from '@/lib/auth';

function Row({ label, ok, text }: { label: string; ok: boolean | null; text: string }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 text-sm">
      <span className="text-mute">{label}</span>
      <span className={`inline-flex items-center gap-1.5 font-medium ${ok === null ? '' : ok ? 'text-ok' : 'text-warn'}`}>
        {ok === true && <Check size={14} aria-hidden />}
        {ok === false && <X size={14} aria-hidden />}
        {text}
      </span>
    </div>
  );
}

export default function SettingsPage() {
  const prefs = usePrefs();
  const records = useProjectRecords();
  const health = useHealth();
  const [confirm, setConfirm] = useState(false);
  const auth = useAuth();

  return (
    <div className="max-w-3xl space-y-10">
      <div>
        <h1 className="text-3xl font-bold">Settings</h1>
        <p className="mt-1 text-mute">Defaults apply to every new Reel. You can still change them per Reel.</p>
      </div>

      <section aria-labelledby="defaults">
        <h2 id="defaults" className="mb-5 text-xl font-semibold">Default style</h2>
        <VideoSettings value={prefs} onChange={setPrefs} />
        <p className="mt-4 text-xs text-mute">Saved automatically in this browser.</p>
      </section>

      {auth.enabled && (
        <section aria-labelledby="account" className="card flex flex-wrap items-center justify-between gap-3 p-5">
          <div>
            <h2 id="account" className="text-xl font-semibold">Account</h2>
            <p className="mt-1 text-sm text-mute">{auth.email ?? 'Signed in'}</p>
          </div>
          <Button variant="secondary" size="sm" onClick={auth.signOut}>Sign out</Button>
        </section>
      )}

      <section aria-labelledby="server" className="card px-5 py-2">
        <h2 id="server" className="pb-1 pt-3 text-xl font-semibold">Server</h2>
        <div className="divide-y divide-line">
          <Row label="Address" ok={null} text={API_BASE} />
          <Row
            label="Connection"
            ok={health.isError ? false : health.data ? true : null}
            text={health.isError ? 'Not reachable' : health.data ? `Connected (v${health.data.version})` : 'Checking…'}
          />
          {health.data && (
            <>
              <Row label="Video rendering (FFmpeg)" ok={health.data.ffmpeg_available} text={health.data.ffmpeg_available ? 'Available' : 'Missing'} />
              <Row label="Job queue" ok={null} text={health.data.redis_available ? 'Redis worker' : 'Built-in worker'} />
            </>
          )}
        </div>
      </section>

      <section aria-labelledby="data" className="card p-5">
        <h2 id="data" className="text-xl font-semibold">Your list</h2>
        <p className="mt-2 text-sm leading-relaxed text-mute">
          Your Reel list is loaded from the server, so clearing it here only hides the cached copy until the next refresh. Use Delete on a Reel to remove a video from the server.
        </p>
        <Button variant="danger" size="sm" className="mt-4" disabled={records.length === 0} onClick={() => setConfirm(true)}>
          Clear local cache ({records.length})
        </Button>
      </section>

      <Modal
        open={confirm}
        onClose={() => setConfirm(false)}
        title="Clear the local cache?"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirm(false)}>Cancel</Button>
            <Button variant="danger" onClick={() => (clearProjects(), setConfirm(false))}>Clear cache</Button>
          </>
        }
      >
        The list is rebuilt from the server the next time you open the dashboard. Nothing is deleted from the server.
      </Modal>
    </div>
  );
}
