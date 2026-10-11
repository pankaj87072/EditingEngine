import type { CaptionStyle, EditingStyle, Intensity, ReelSettings, SubtitlePosition, TTSProvider } from '@/types';

export const DEFAULT_SETTINGS: ReelSettings = {
  ttsProvider: 'auto',
  editingStyle: 'clean',
  intensity: 'balanced',
  captionStyle: 'classic',
  subtitlePosition: 'bottom',
};

interface Option<T> {
  value: T;
  label: string;
  hint: string;
}

export const VOICES: Option<TTSProvider>[] = [
  { value: 'auto', label: 'Best available', hint: 'Uses the natural voice when the server has one, otherwise the standard voice.' },
  { value: 'google', label: 'Standard voice', hint: 'Clear and reliable. Works out of the box.' },
  { value: 'elevenlabs', label: 'Natural voice', hint: 'Expressive; follows your [Excited] style directions. Needs an ElevenLabs key on the server.' },
];

export const EDITING_STYLES: Option<EditingStyle>[] = [
  { value: 'clean', label: 'Clean', hint: 'Simple cuts, subtle movement, readable captions.' },
  { value: 'social_punchy', label: 'Social Punchy', hint: 'Faster cuts, emphasis moments, stronger motion.' },
  { value: 'cinematic', label: 'Cinematic', hint: 'Longer shots, smooth movement, subtle transitions.' },
  { value: 'dynamic', label: 'Dynamic', hint: 'More visual changes, stronger motion and energetic pacing.' },
  { value: 'storytelling', label: 'Storytelling', hint: 'Longer visual continuity and scene-aware cuts.' },
  { value: 'product_focus', label: 'Product Focus', hint: 'Keeps products and subjects prominent, captions clear.' },
];

export const INTENSITIES: Option<Intensity>[] = [
  { value: 'calm', label: 'Calm', hint: 'Gentler movement and slightly longer shots.' },
  { value: 'balanced', label: 'Balanced', hint: 'The style’s normal pacing and movement.' },
  { value: 'dynamic', label: 'Dynamic', hint: 'Stronger movement and slightly faster cuts.' },
];

export const CAPTION_STYLES: Option<CaptionStyle>[] = [
  { value: 'classic', label: 'Classic', hint: 'White text, black outline.' },
  { value: 'bold', label: 'Bold', hint: 'Larger and heavier. Easy to read on small screens.' },
  { value: 'soft', label: 'Soft', hint: 'Smaller and lighter. Keeps the picture clear.' },
];

export const POSITIONS: Option<SubtitlePosition>[] = [
  { value: 'bottom', label: 'Lower third', hint: 'Above the platform buttons.' },
  { value: 'center', label: 'Middle', hint: 'Centered on screen.' },
  { value: 'upper', label: 'Upper safe area', hint: 'Near the top, clear of app buttons.' },
];

export const labelOf = <T extends string>(list: Option<T>[], v: T) => list.find((o) => o.value === v)?.label ?? v;
