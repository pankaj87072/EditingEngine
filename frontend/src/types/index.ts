// Mirrors backend models/schema.py
export type JobState = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';
export type TTSProvider = 'auto' | 'google' | 'elevenlabs';
export type EditingStyle = 'clean' | 'social_punchy' | 'cinematic' | 'dynamic' | 'storytelling' | 'product_focus';
export type SubtitlePosition = 'bottom' | 'center' | 'upper';
export type CaptionStyle = 'classic' | 'bold' | 'soft';
export type Intensity = 'calm' | 'balanced' | 'dynamic';

export interface JobStatus {
  job_id: string;
  status: JobState;
  progress: number;
  current_stage: string;
  created_at: string;
  updated_at: string;
  error?: string | null;
}

export interface QualityReport {
  ok: boolean;
  errors: string[];
  warnings: string[];
  file_size_mb?: number;
  video?: { width: number; height: number; fps: number; codec?: string; duration: number };
  audio?: boolean;
  captions?: { expected: boolean; entries: number };
  decode_ok?: boolean;
  voice?: { provider: string; fallback_used: boolean; timing_source: string };
  timings?: Record<string, number>;
}

export interface JobResult {
  job_id: string;
  status: JobState;
  output_url?: string | null;
  message: string;
  report?: QualityReport | null;
}

export interface HealthInfo {
  status: string;
  app: string;
  version: string;
  timestamp: string;
  ffmpeg_available: boolean;
  redis_available: boolean;
}

export interface ReelSettings {
  ttsProvider: TTSProvider;
  editingStyle: EditingStyle;
  intensity: Intensity;
  captionStyle: CaptionStyle;
  subtitlePosition: SubtitlePosition;
}

/** Stored locally – the backend has no "list jobs" endpoint. */
export interface ProjectRecord {
  jobId: string;
  title: string;
  script: string;
  settings: ReelSettings;
  clipCount: number;
  createdAt: string;
  durationSec?: number;
}

export type ClipState = 'reading' | 'ready' | 'unreadable';

export interface ClipItem {
  id: string;
  file: File;
  name: string;
  size: number;
  state: ClipState;
  duration?: number;
  width?: number;
  height?: number;
  thumb?: string; // small JPEG data URL
}

/** GET /result/{id}/plan: the editing plan the backend actually used (one entry per shot). */
export interface PlanScene {
  scene_index: number;
  shot_index: number;
  script_segment: string;
  scene_role: 'hook' | 'intro' | 'body' | 'payoff' | 'cta';
  clip: string;
  start: number;
  end: number;
  duration: number;
  crop: 'left' | 'center' | 'right';
  crop_x: number | null;
  zoom: number | null;
  speed: number;
  motion: string;
  effect: string;
  join_after: string;
  caption_emphasis: string[];
  why: string;
  planned_by: 'ai' | 'rules' | 'default';
}
export interface EditingPlan {
  editing_style: EditingStyle;
  editing_style_label: string;
  planner?: 'ai' | 'rules';
  scenes: PlanScene[];
}
