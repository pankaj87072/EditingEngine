import { Sparkles } from 'lucide-react';
import { useJobPlan } from '@/hooks/useJob';
import { formatDuration } from '@/utils/format';

const MOTION_LABEL: Record<string, string> = {
  static: 'Static hold', push_in: 'Push in', pull_out: 'Pull out', pan_h: 'Horizontal pan', pan_v: 'Vertical pan',
  dynamic_push: 'Dynamic push', punch: 'Punch zoom', cinematic_drift: 'Cinematic drift',
};
const JOIN_LABEL: Record<string, string> = {
  cut: 'cut', dissolve: 'dissolve', smoothleft: 'slide', zoomin: 'zoom blend', fadeblack: 'dip to black', legacy: 'fade',
};
const ROLE_LABEL: Record<string, string> = { hook: 'Hook', intro: 'Intro', body: 'Body', payoff: 'Payoff', cta: 'Call to action' };

/** Real plan from GET /result/{id}/plan. Hidden if the server has none (older Reels). */
export function EditingPlanPanel({ jobId }: { jobId: string }) {
  const plan = useJobPlan(jobId);
  if (plan.isPending || plan.isError || !plan.data?.scenes.length) return null;
  const { scenes, editing_style_label: style, planner } = plan.data;
  const ai = planner === 'ai' || scenes.some((s) => s.planned_by === 'ai');

  return (
    <details className="card px-4 py-3 text-sm">
      <summary className="flex cursor-pointer items-center gap-2 font-medium">
        <Sparkles size={15} className="text-violet" aria-hidden />
        How this was edited
        <span className="ml-auto text-xs font-normal text-mute">
          {style ? `${style}, ` : ''}{ai ? 'refined with AI' : 'built-in rules'}
        </span>
      </summary>
      <ol className="mt-4 space-y-3">
        {scenes.map((s) => (
          <li key={`${s.scene_index}-${s.shot_index}`} className="rounded-xl border border-line bg-bg p-3">
            <p className="flex items-center gap-2 text-xs text-mute">
              <span className="rounded bg-raised px-1.5 py-0.5 font-medium text-ink">{ROLE_LABEL[s.scene_role] ?? s.scene_role}</span>
              {formatDuration(s.duration)}
              {s.planned_by === 'ai' && <span className="text-violet">AI</span>}
            </p>
            <p className="mt-1.5 leading-snug">“{s.script_segment}”</p>
            <p className="mt-2 text-xs leading-relaxed text-mute">
              <span className="text-ink">{s.clip}</span> from {s.start.toFixed(1)}s to {s.end.toFixed(1)}s.{' '}
              {MOTION_LABEL[s.motion] ?? s.motion}
              {s.zoom && s.zoom > 1 ? ` (${s.zoom.toFixed(2)}×)` : ''}
              {s.speed !== 1 ? `, speed ${s.speed.toFixed(2)}×` : ''}
              {s.crop !== 'center' ? `, crop ${s.crop}` : ''}. Then a {JOIN_LABEL[s.join_after] ?? s.join_after}.
              {s.caption_emphasis.length > 0 && (
                <> Highlighted: {s.caption_emphasis.map((w) => (
                  <mark key={w} className="mr-1 rounded bg-warn/20 px-1 text-warn">{w}</mark>
                ))}</>
              )}
            </p>
            {s.why && <p className="mt-1.5 text-xs text-mute/80">{s.why}</p>}
          </li>
        ))}
      </ol>
    </details>
  );
}
