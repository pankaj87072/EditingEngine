"""
models/schema.py
----------------
All Pydantic models / dataclasses used by agents, services, and API.
Keeping models in one place prevents circular imports.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    COMPLETED  = "completed"
    FAILED     = "failed"
    CANCELLED  = "cancelled"


class TransitionType(str, Enum):
    FADE       = "fade"
    CROSSFADE  = "crossfade"
    ZOOM       = "zoom"
    NONE       = "none"


class TTSProvider(str, Enum):
    AUTO       = "auto"        # ElevenLabs when configured, otherwise Google
    GOOGLE     = "google"
    ELEVENLABS = "elevenlabs"


class SubtitlePosition(str, Enum):
    BOTTOM = "bottom"   # previous behaviour (default)
    CENTER = "center"
    UPPER  = "upper"    # upper safe area


class CaptionStyle(str, Enum):
    CLASSIC = "classic"  # previous behaviour (default)
    BOLD    = "bold"
    SOFT    = "soft"


class EditingStyle(str, Enum):
    CLEAN         = "clean"
    SOCIAL_PUNCHY = "social_punchy"
    CINEMATIC     = "cinematic"
    DYNAMIC       = "dynamic"
    STORYTELLING  = "storytelling"
    PRODUCT_FOCUS = "product_focus"


class EditingIntensity(str, Enum):
    CALM     = "calm"
    BALANCED = "balanced"  # previous behaviour (ZOOM_INTENSITY=1.10)
    DYNAMIC  = "dynamic"


# ── Script / Scene models ─────────────────────────────────────────────────────

class ScriptScene(BaseModel):
    """One logical scene extracted from the script."""
    scene_index: int
    text: str
    word_count: int
    estimated_duration: float          # seconds
    keywords: List[str] = Field(default_factory=list)
    # ── Script-aware fields (optional; filled by ScriptSegmentationAgent) ─────
    role: str = "body"                       # hook | intro | body | payoff | cta
    intent: str = "generic"                  # problem | product | action | result | emotion | people | place | screen | food | generic
    energy: float = 0.5                      # 0..1 suggested editing energy
    nouns: List[str] = Field(default_factory=list)
    verbs: List[str] = Field(default_factory=list)
    important_words: List[str] = Field(default_factory=list)
    visual_intent: List[str] = Field(default_factory=list)
    # ── Delivery metadata (from "[Excited, energetic]" style directions; see agents/delivery.py) ──
    emotion: str = "neutral"                 # excited | curious | mysterious | suspense | confident | serious | calm | playful | ...
    delivery: str = "neutral"                # punchy | suspense | authoritative | informative | warning | warm | whisper | neutral
    speech_speed: float = 1.0                # 0.8..1.2 TTS speaking-rate multiplier
    tts_energy: Optional[float] = None       # 0..1 from the direction (None = no direction given)
    pause_before: float = 0.0                # seconds of silence before the line
    pause_after: float = 0.0                 # seconds of silence after the line
    directive: str = ""                      # the raw "[...]" text (never spoken, never captioned)


class SceneMappingResult(BaseModel):
    """Which clip file was assigned to which scene."""
    scene_index: int
    clip_path: str                     # absolute path
    clip_duration: float               # seconds
    scene_text: str
    # ── Editing-plan fields (all optional; None/defaults = previous behaviour) ──
    start: float = 0.0                 # where in the source clip to start (s)
    duration: Optional[float] = None   # how long this scene shows on screen (s)
    crop: str = "center"               # left | center | right (for non-vertical clips)
    zoom: Optional[float] = None       # Ken Burns ceiling for this scene
    caption_emphasis: List[str] = Field(default_factory=list)
    planned_by: str = "default"        # "ai" | "rules" | "default"
    # ── Shot-level plan (a scene may be cut into several shots) ───────────────
    shot_index: int = 0
    word_range: Optional[List[int]] = None   # [first, last+1] word indices inside the scene
    scene_role: str = "body"
    visual_energy: float = 0.5
    speed: float = 1.0                 # 0.85..1.2, conservative
    motion: str = "push_in"            # see core.editing_rules.MOTION_PRESETS
    punch_at: Optional[float] = None   # seconds into the shot for a punch-in on an emphasis word
    crop_x: Optional[float] = None     # 0..1 position of the crop window on the source (None = use `crop`)
    effect: str = "none"
    join_after: str = "legacy"         # cut | dissolve | smoothleft | zoomin | fadeblack | legacy
    join_dur: float = 0.0
    subject_y: Optional[float] = None  # 0..1, used to keep captions off the subject
    why: str = ""                      # human-readable reason this segment was chosen
    candidates: List[dict] = Field(default_factory=list)  # top alternatives with scores


# ── Audio / Subtitle models ───────────────────────────────────────────────────

class WordTiming(BaseModel):
    """Timing for a single word (word-level subtitle support)."""
    word: str
    start_time: float                  # seconds from audio start
    end_time: float


class SubtitleEntry(BaseModel):
    """One subtitle block (may contain multiple words)."""
    index: int
    start_time: float
    end_time: float
    text: str


class AudioResult(BaseModel):
    """Output from AudioGenerationAgent."""
    audio_path: str                    # absolute path to .mp3/.wav
    duration: float                    # total audio duration in seconds
    provider: TTSProvider
    word_timings: List[WordTiming] = Field(default_factory=list)
    timing_source: str = "none"              # provider | scene-estimate | none
    fallback_used: bool = False              # True if the preferred voice failed and another was used
    warnings: List[str] = Field(default_factory=list)


# ── Job models ────────────────────────────────────────────────────────────────

class JobCreateRequest(BaseModel):
    """Parsed from multipart form data by the route layer."""
    script: str
    tts_provider: TTSProvider = TTSProvider.GOOGLE
    transition: TransitionType = TransitionType.FADE


class Job(BaseModel):
    """Persisted job record stored in JSON on disk."""
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Input
    script: str = ""
    tts_provider: TTSProvider = TTSProvider.GOOGLE
    transition: TransitionType = TransitionType.FADE
    subtitle_position: SubtitlePosition = SubtitlePosition.BOTTOM
    caption_style: CaptionStyle = CaptionStyle.CLASSIC
    intensity: EditingIntensity = EditingIntensity.BALANCED
    editing_style: EditingStyle = EditingStyle.CLEAN
    transition_override: Optional[TransitionType] = None   # only if the client sent `transition` explicitly
    report: Optional[dict] = None
    clip_paths: List[str] = Field(default_factory=list)   # uploaded clips
    owner_id: Optional[str] = None                        # set when AUTH_ENABLED

    # Processing progress (0–100)
    progress: int = 0
    current_stage: str = ""

    # Output
    output_path: Optional[str] = None
    output_url: Optional[str] = None
    error: Optional[str] = None

    # Intermediate artifacts (for debugging / resuming)
    scenes: List[ScriptScene] = Field(default_factory=list)
    scene_mappings: List[SceneMappingResult] = Field(default_factory=list)
    subtitles: List[SubtitleEntry] = Field(default_factory=list)
    audio_result: Optional[AudioResult] = None

    def touch(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.utcnow()

    def set_stage(self, stage: str, progress: int) -> None:
        self.current_stage = stage
        self.progress = progress
        self.touch()


# ── API response schemas ──────────────────────────────────────────────────────

class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: int
    current_stage: str
    created_at: datetime
    updated_at: datetime
    error: Optional[str] = None


class JobResultResponse(BaseModel):
    job_id: str
    status: JobStatus
    output_url: Optional[str] = None
    message: str
    report: Optional[dict] = None      # technical validation of the rendered file
