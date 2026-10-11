import type { CSSProperties } from 'react';
import { CAPTION_STYLES, POSITIONS } from '@/lib/options';
import type { CaptionStyle, SubtitlePosition } from '@/types';
import { RadioCards } from './RadioCards';

const sample: Record<CaptionStyle, CSSProperties> = {
  classic: { fontWeight: 600, fontSize: 18, textShadow: '0 0 3px #000, 0 0 3px #000, 0 1px 4px #000' },
  bold: { fontWeight: 800, fontSize: 23, textShadow: '0 0 4px #000, 0 0 4px #000, 0 0 6px #000' },
  soft: { fontWeight: 500, fontSize: 15, textShadow: '0 1px 3px rgb(0 0 0 / .8)' },
};

interface Props {
  style: CaptionStyle;
  position: SubtitlePosition;
  onStyle: (s: CaptionStyle) => void;
  onPosition: (p: SubtitlePosition) => void;
}

export function CaptionStyleSelector({ style, position, onStyle, onPosition }: Props) {
  return (
    <div className="space-y-6">
      <RadioCards
        name="caption-style"
        legend="Caption style"
        help="Captions are generated from your script and timed to the voiceover."
        value={style}
        options={CAPTION_STYLES}
        onChange={onStyle}
        columns="grid-cols-1 sm:grid-cols-3"
        render={(o) => (
          <>
            <div className="mb-2.5 grid h-16 place-items-center rounded-lg bg-gradient-to-br from-slate-700 to-slate-900">
              <span className="text-white" style={sample[o.value]}>
                Your words
              </span>
            </div>
            <span className="block text-sm font-medium">{o.label}</span>
            <span className="mt-0.5 block text-xs leading-snug text-mute">{o.hint}</span>
          </>
        )}
      />
      <RadioCards
        name="caption-position"
        legend="Caption position"
        value={position}
        options={POSITIONS}
        onChange={onPosition}
        render={(o) => (
          <div className="flex items-center gap-3">
            <div className="relative h-14 w-8 shrink-0 rounded-md border border-mute/50 bg-bg" aria-hidden>
              <span
                className="absolute inset-x-1 h-1.5 rounded-sm bg-violet"
                style={{ top: o.value === 'center' ? '45%' : '68%' }}
              />
            </div>
            <div>
              <span className="block text-sm font-medium">{o.label}</span>
              <span className="mt-0.5 block text-xs leading-snug text-mute">{o.hint}</span>
            </div>
          </div>
        )}
      />
    </div>
  );
}
