import { CheckCircle2, AlertTriangle } from 'lucide-react';
import type { QualityReport } from '@/types';

/** Technical check the server ran on the rendered file. Hidden for Reels made before it existed. */
export function QualityPanel({ report }: { report?: QualityReport | null }) {
  if (!report) return null;
  const v = report.video;
  const items = [
    v && `${v.width}×${v.height}, ${Math.round(v.fps)} fps${v.codec ? `, ${v.codec.toUpperCase()}` : ''}`,
    report.audio ? `Voiceover${report.voice ? ` (${report.voice.provider === 'elevenlabs' ? 'natural voice' : 'standard voice'})` : ''}` : 'No audio',
    report.captions?.expected && `${report.captions.entries} caption cards`,
    report.decode_ok && 'Plays back cleanly',
    report.timings?.total != null && `Made in ${Math.round(report.timings.total)}s`,
  ].filter(Boolean) as string[];
  const clean = report.ok && report.warnings.length === 0;

  return (
    <section aria-label="Quality check" className="card px-4 py-3 text-sm">
      <h2 className="flex items-center gap-2 font-medium">
        {clean ? <CheckCircle2 size={16} className="text-ok" aria-hidden /> : <AlertTriangle size={16} className="text-warn" aria-hidden />}
        Quality check {clean ? 'passed' : 'passed with notes'}
      </h2>
      <p className="mt-2 text-mute">{items.join(' · ')}</p>
      {report.warnings.length > 0 && (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-warn">
          {report.warnings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      )}
    </section>
  );
}
