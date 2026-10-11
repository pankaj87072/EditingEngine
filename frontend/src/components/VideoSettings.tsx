import { RotateCcw } from 'lucide-react';
import { DEFAULT_SETTINGS, EDITING_STYLES, INTENSITIES, VOICES } from '@/lib/options';
import type { ReelSettings } from '@/types';
import { Button } from './Button';
import { CaptionStyleSelector } from './CaptionStyleSelector';
import { RadioCards } from './RadioCards';

interface Props {
  value: ReelSettings;
  onChange: (s: ReelSettings) => void;
}

/** Every option here is sent to the backend – nothing decorative. */
export function VideoSettings({ value, onChange }: Props) {
  const set = <K extends keyof ReelSettings>(k: K) => (v: ReelSettings[K]) => onChange({ ...value, [k]: v });
  const isDefault = JSON.stringify(value) === JSON.stringify(DEFAULT_SETTINGS);

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between gap-3 rounded-xl border border-line bg-surface px-4 py-3">
        <p className="text-sm text-mute">The defaults work well for most scripts. Change only what you want.</p>
        <Button variant="ghost" size="sm" disabled={isDefault} onClick={() => onChange(DEFAULT_SETTINGS)}>
          <RotateCcw size={14} aria-hidden /> Reset
        </Button>
      </div>
      <RadioCards name="voice" legend="Voice" help="Reads your script aloud. If the natural voice is unavailable, the standard voice is used automatically." value={value.ttsProvider} options={VOICES} onChange={set('ttsProvider')} columns="sm:grid-cols-3" />
      <RadioCards name="editing-style" legend="Editing style" help="Sets pacing, cut rhythm, camera movement and transitions together." value={value.editingStyle} options={EDITING_STYLES} onChange={set('editingStyle')} columns="sm:grid-cols-2 lg:grid-cols-3" />
      <RadioCards name="intensity" legend="Editing intensity" help="Scales the style up or down." value={value.intensity} options={INTENSITIES} onChange={set('intensity')} columns="sm:grid-cols-3" />
      <CaptionStyleSelector style={value.captionStyle} position={value.subtitlePosition} onStyle={set('captionStyle')} onPosition={set('subtitlePosition')} />
    </div>
  );
}
