import { useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Check, Info, Loader2, Sparkles } from 'lucide-react';
import { Button } from '@/components/Button';
import { ClipUploader } from '@/components/ClipUploader';
import { VideoSettings } from '@/components/VideoSettings';
import { ProgressBar } from '@/components/Progress';
import { ErrorState } from '@/components/ErrorState';
import { ServerNotice } from '@/components/ServerNotice';
import { createJob } from '@/api/jobs';
import { friendlyMessage } from '@/api/client';
import { useDraft } from '@/lib/draft';
import { addProject } from '@/lib/projects';
import { CAPTION_STYLES, EDITING_STYLES, INTENSITIES, labelOf, POSITIONS, VOICES } from '@/lib/options';
import { analyzeScript, MIN_WORDS, titleFromScript } from '@/utils/script';
import { formatBytes, formatDuration } from '@/utils/format';
import { cn } from '@/lib/cn';

const STEPS = ['Script', 'Clips', 'Style', 'Generate'] as const;

const EXAMPLE =
  "Most people edit their videos backwards. They start with effects, and the story comes last. Flip it. Write the script first, then choose clips that show every line. Keep each shot short and cut when the idea changes. Follow for more simple editing tips.";

export default function NewReel() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const { script, setScript, settings, setSettings, clips, reset } = useDraft();
  const [step, setStep] = useState(params.get('from') === 'edit' ? 1 : 0);
  const [uploading, setUploading] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  const info = useMemo(() => analyzeScript(script), [script]);
  const readyClips = clips.filter((c) => c.state !== 'reading');
  const totalClipSec = clips.reduce((s, c) => s + (c.duration ?? 0), 0);
  const totalBytes = clips.reduce((s, c) => s + c.size, 0);

  const canNext = step === 0 ? info.ready : step === 1 ? readyClips.length > 0 && readyClips.length === clips.length : true;
  const blocker =
    step === 0 && !info.ready
      ? `Write at least ${MIN_WORDS} words to continue.`
      : step === 1 && clips.length === 0
        ? 'Add at least one clip to continue.'
        : step === 1 && !canNext
          ? 'Reading your clips…'
          : null;

  const generate = async () => {
    setError(null);
    setUploading(0);
    abort.current = new AbortController();
    try {
      const res = await createJob(
        { script, clips, settings },
        { onProgress: (f) => setUploading(f), signal: abort.current.signal },
      );
      addProject({
        jobId: res.job_id,
        title: titleFromScript(script),
        script,
        settings,
        clipCount: clips.length,
        createdAt: new Date().toISOString(),
      });
      reset();
      nav(`/reels/${res.job_id}`);
    } catch (e) {
      const msg = friendlyMessage(e);
      if (msg !== 'Cancelled.') setError(msg);
      setUploading(null);
    }
  };

  return (
    <div className="space-y-6 pb-24 lg:pb-0">
      <div>
        <h1 className="text-3xl font-bold">New Reel</h1>
        <ol className="mt-5 flex gap-2" aria-label="Progress">
          {STEPS.map((s, i) => (
            <li key={s} className="flex-1" aria-current={i === step ? 'step' : undefined}>
              <button
                type="button"
                disabled={i > step || uploading !== null}
                onClick={() => setStep(i)}
                className={cn(
                  'w-full rounded-lg border-t-[3px] pt-2 text-left text-sm transition-colors disabled:cursor-default',
                  i < step ? 'border-violet text-ink' : i === step ? 'border-azure text-ink' : 'border-line text-mute',
                )}
              >
                <span className="sr-only">Step {i + 1}: </span>
                {s}
                {i < step && <Check size={13} className="ml-1.5 inline text-ok" aria-label="completed" />}
              </button>
            </li>
          ))}
        </ol>
      </div>

      <ServerNotice />

      <div className="grid gap-8 lg:grid-cols-[1fr_20rem]">
        <section aria-live="polite" className="min-w-0">
          {step === 0 && (
            <div className="space-y-5">
              <div>
                <label htmlFor="script" className="text-lg font-semibold">What should your video say?</label>
                <p className="mt-1 text-sm text-mute">Paste your script. It is read aloud and captioned. To control the delivery, put a direction in square brackets before a line, like <span className="text-ink">[Excited, energetic]</span> or <span className="text-ink">[Calm, serious]</span>. Directions are never spoken or shown.</p>
              </div>
              <textarea
                id="script"
                value={script}
                onChange={(e) => setScript(e.target.value)}
                maxLength={6000}
                rows={11}
                placeholder="Start with a line that makes people stop scrolling…"
                className="field resize-y text-base leading-relaxed"
              />
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-mute">
                <span>
                  {info.chars.toLocaleString()} / 6,000 characters, {info.words} spoken words
                  {info.directions > 0 && `, ${info.directions} voice direction${info.directions === 1 ? '' : 's'}`}
                </span>
                <span className={info.seconds > 60 ? 'text-warn' : ''}>
                  {info.words ? `About ${formatDuration(info.seconds)} of video` : 'Length appears as you type'}
                </span>
                {!script && (
                  <button type="button" className="font-medium text-azure hover:underline" onClick={() => setScript(EXAMPLE)}>
                    Use an example script
                  </button>
                )}
              </div>

              {info.words > 0 && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="card p-4">
                    <h3 className="text-sm font-semibold">Opening line</h3>
                    <p className="mt-2 text-sm leading-relaxed">“{info.hook}”</p>
                    {info.hookTip && (
                      <p className="mt-2 flex gap-1.5 text-xs text-warn">
                        <Info size={14} className="mt-px shrink-0" aria-hidden /> {info.hookTip}
                      </p>
                    )}
                  </div>
                  <div className="card p-4">
                    <h3 className="text-sm font-semibold">Call to action</h3>
                    {info.cta ? (
                      <p className="mt-2 text-sm leading-relaxed text-ok">Found: “{info.cta}”</p>
                    ) : (
                      <p className="mt-2 text-sm leading-relaxed text-mute">None detected. Ending with an action, like “Follow for more”, gives viewers a next step.</p>
                    )}
                  </div>
                </div>
              )}
              {info.seconds > 60 && (
                <p className="text-sm text-warn">This script is over a minute long. Shorter scripts usually suit short-form platforms better.</p>
              )}
            </div>
          )}

          {step === 1 && (
            <div className="space-y-5">
              <div>
                <h2 className="text-lg font-semibold">Add your clips</h2>
                <p className="mt-1 text-sm text-mute">
                  Your script will be cut into about {info.scenes} {info.scenes === 1 ? 'scene' : 'scenes'}. One or two clips is fine; they’re reused when needed.
                </p>
              </div>
              {params.get('from') === 'edit' && clips.length === 0 && (
                <p className="rounded-xl border border-azure/30 bg-azure/10 p-3 text-sm text-azure">
                  Your script and style are restored. Clips aren’t kept after a Reel finishes, so add them again to generate a new version.
                </p>
              )}
              <ClipUploader />
            </div>
          )}

          {step === 2 && (
            <div className="space-y-5">
              <h2 className="text-lg font-semibold">Choose a style</h2>
              <VideoSettings value={settings} onChange={setSettings} />
            </div>
          )}

          {step === 3 && (
            <div className="space-y-5">
              <h2 className="text-lg font-semibold">Ready to generate</h2>
              <dl className="card divide-y divide-line text-sm">
                <SummaryRow label="Script" value={`${info.words} words, about ${formatDuration(info.seconds)}`} detail={`“${info.hook}”`} />
                <SummaryRow label="Clips" value={`${clips.length} ${clips.length === 1 ? 'clip' : 'clips'}, ${formatBytes(totalBytes)}`} detail={totalClipSec ? `${formatDuration(totalClipSec)} of footage` : undefined} />
                <SummaryRow label="Voice" value={labelOf(VOICES, settings.ttsProvider)} />
                <SummaryRow
                  label="Style"
                  value={`${labelOf(EDITING_STYLES, settings.editingStyle)} style, ${labelOf(INTENSITIES, settings.intensity).toLowerCase()} intensity`}
                  detail={`${labelOf(CAPTION_STYLES, settings.captionStyle)} captions, ${labelOf(POSITIONS, settings.subtitlePosition).toLowerCase()}`}
                />
                <SummaryRow label="Output" value="1080×1920 vertical MP4 (H.264)" />
              </dl>

              {uploading !== null && (
                <div className="card space-y-3 p-4" role="status">
                  <div className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2"><Loader2 size={16} className="animate-spin" aria-hidden /> Uploading your clips</span>
                    <span className="tabular-nums text-mute">{Math.round(uploading * 100)}%</span>
                  </div>
                  <ProgressBar value={uploading * 100} label="Upload progress" />
                  <Button variant="ghost" size="sm" onClick={() => abort.current?.abort()}>Cancel upload</Button>
                </div>
              )}
              {error && <ErrorState compact title="Couldn’t start your Reel" message={error} onRetry={generate} />}
            </div>
          )}

          {/* Step actions */}
          <div className="fixed inset-x-0 bottom-[calc(3.5rem+env(safe-area-inset-bottom))] z-20 border-t border-line bg-bg/95 px-4 py-3 backdrop-blur lg:static lg:mt-8 lg:border-0 lg:bg-transparent lg:p-0 lg:backdrop-blur-none">
            {blocker && <p className="mb-2 text-xs text-mute lg:mb-3 lg:text-sm">{blocker}</p>}
            <div className="flex gap-3">
              {step > 0 && (
                <Button variant="secondary" size="lg" disabled={uploading !== null} onClick={() => setStep(step - 1)}>
                  <ArrowLeft size={16} aria-hidden /> Back
                </Button>
              )}
              {step < 3 ? (
                <Button size="lg" className="flex-1 lg:flex-none" disabled={!canNext} onClick={() => setStep(step + 1)}>
                  Continue
                </Button>
              ) : (
                <Button size="lg" className="flex-1 lg:flex-none" disabled={uploading !== null || clips.length === 0 || !info.ready} onClick={generate}>
                  <Sparkles size={18} aria-hidden /> Generate Reel
                </Button>
              )}
            </div>
          </div>
        </section>

        <aside className="hidden lg:block">
          <div className="card sticky top-10 space-y-4 p-5 text-sm">
            <h2 className="text-base font-semibold">Your Reel</h2>
            <Stat label="Script" value={info.words ? `${info.words} words` : 'Not written yet'} />
            <Stat label="Estimated length" value={info.words ? formatDuration(info.seconds) : '–'} />
            <Stat label="Scenes" value={info.words ? `About ${info.scenes}` : '–'} />
            <Stat label="Clips" value={clips.length ? `${clips.length} added` : 'None yet'} />
            <Stat label="Output" value="1080×1920 MP4" />
            <p className="border-t border-line pt-3 text-xs leading-relaxed text-mute">
              Final length follows the voiceover. Your footage is never altered beyond cropping, zoom and transitions.
            </p>
            <Link to="/app" className="text-xs text-mute hover:text-ink">Back to dashboard</Link>
          </div>
        </aside>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-mute">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  );
}

function SummaryRow({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="grid gap-1 px-4 py-3.5 sm:grid-cols-[6rem_1fr] sm:gap-4">
      <dt className="text-mute">{label}</dt>
      <dd>
        <span className="font-medium">{value}</span>
        {detail && <span className="mt-0.5 block text-mute">{detail}</span>}
      </dd>
    </div>
  );
}
