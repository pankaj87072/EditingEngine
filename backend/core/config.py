"""
core/config.py
--------------
Central configuration loaded from environment variables.
All settings live here — no scattered os.getenv() calls in business logic.
"""

import os
from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────────────────
    APP_NAME: str = "AutoVideoGen"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # ── Storage ───────────────────────────────────────────────────────────────
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    UPLOADS_DIR: Path = DATA_DIR / "uploads"
    OUTPUTS_DIR: Path = DATA_DIR / "outputs"

    # ── Redis / Celery ────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # ── TTS Provider ─────────────────────────────────────────────────────────
    # Accepted values: "google" | "elevenlabs"
    TTS_PROVIDER: Literal["auto", "google", "elevenlabs"] = "auto"

    # Google TTS
    GOOGLE_TTS_LANGUAGE: str = "en-IN"          # Indian English suits Hinglish; use hi-IN for Devanagari scripts
    GOOGLE_TTS_VOICE: str = "en-IN-Neural2-B"

    # ElevenLabs
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = "21m00Tcm4TlvDq8ikWAM"  # Default: Rachel. For Hinglish choose a voice with an Indian accent.
    ELEVENLABS_MODEL: str = "eleven_multilingual_v2"   # "eleven_v3" switches to inline audio tags ([excited]) instead of voice settings
    ELEVENLABS_TIMEOUT: float = 60.0
    ELEVENLABS_RETRIES: int = 2
    TTS_MAX_CONCURRENCY: int = 3                       # parallel scene syntheses (API rate limits!)
    TTS_CACHE: bool = True
    SCENE_GAP: float = 0.08                            # silence between scenes (s), on top of any [pause]

    # ── Video analysis / vision (all optional & degrade gracefully) ───────────
    ZOOM_PRESCALE: float = 1.5               # intermediate upscale for smooth zoompan (1.0 = faster, 2.0 = smoothest)
    SINGLE_PASS_COMPOSITION: bool = True     # ONE FFmpeg filter graph + ONE encode (falls back to the multi-stage path on error)
    MOTION_ENGINE: str = "zoompan"          # "zoompan" (original look, default) or "scale" (~5% faster, per-frame scale+crop)
    VIDEO_PRESET: str = "veryfast"
    VIDEO_CRF: int = 20
    VIDEO_MAXRATE: str = "12M"               # cap so Reels/Shorts uploads stay reasonable
    AUDIO_SAMPLE_RATE: int = 48000
    AUDIO_NORMALIZE: bool = True             # loudnorm to about -16 LUFS (mobile speakers)
    BACKGROUND_MUSIC_PATH: str = ""          # optional music bed; ducked under the narration
    MUSIC_VOLUME: float = 0.18
    ANALYZER_WORKERS: int = 3
    ANALYZER_ENABLED: bool = True
    ANALYZER_MAX_SECONDS: float = 90.0       # only the first N seconds of a clip are sampled
    ANALYZER_MAX_SAMPLES: int = 48           # sampled frames per clip (not every frame)
    ANALYZER_SCENE_DETECT: bool = True       # ffmpeg scene-cut pass
    ANALYZER_FACES: bool = True              # used only if OpenCV is installed
    ANALYZER_SAVE_KEYFRAMES: bool = True     # only generated when VISION_ENABLED (they are only used by vision)
    VISION_ENABLED: bool = False             # send <=3 keyframes/clip to a vision model
    VISION_MODEL: str = "claude-haiku-4-5-20251001"
    VISION_MAX_FRAMES: int = 3
    PLANNER_MAX_SHOTS: int = 40              # skip the AI call above this (cost cap)
    QUALITY_DECODE: str = "edges"            # "edges" (decode first+last 3 s), "full" (whole file) or "off"

    # ── Auth (optional; off by default = single-user, no login) ───────────────
    AUTH_ENABLED: bool = False
    AUTH_SECRET: str = ""            # empty -> generated once and stored in data/.auth_secret
    AUTH_TOKEN_TTL_HOURS: int = 168  # 7 days

    # ── Editing planner (optional LLM) ────────────────────────────────────────
    # One small structured call per Reel decides clip choice, start offsets, crop,
    # zoom and caption emphasis. No key / any failure -> deterministic rules.
    ANTHROPIC_API_KEY: str = ""
    PLANNER_ENABLED: bool = True
    PLANNER_MODEL: str = "claude-haiku-4-5-20251001"
    PLANNER_TIMEOUT: float = 25.0

    # ── Video ─────────────────────────────────────────────────────────────────
    # Output resolution for vertical (9:16) video
    VIDEO_WIDTH: int = 1080
    VIDEO_HEIGHT: int = 1920
    VIDEO_FPS: int = 30
    VIDEO_BITRATE: str = "4M"
    AUDIO_BITRATE: str = "192k"

    # Default transition type: "fade" | "crossfade" | "zoom"
    DEFAULT_TRANSITION: Literal["fade", "crossfade", "zoom"] = "fade"
    TRANSITION_DURATION: float = 0.5  # seconds

    # Ken Burns zoom intensity (1.0 = no zoom, 1.15 = 15% zoom)
    ZOOM_INTENSITY: float = 1.10

    # ── Subtitle ──────────────────────────────────────────────────────────────
    SUBTITLE_FONT: str = "Arial"
    SUBTITLE_FONT_SIZE: int = 60
    SUBTITLE_COLOR: str = "white"
    SUBTITLE_OUTLINE_COLOR: str = "black"
    SUBTITLE_OUTLINE_WIDTH: int = 3
    SUBTITLE_POSITION: str = "center"  # center | bottom

    # ── Script Segmentation ───────────────────────────────────────────────────
    # Average words per second for duration estimation
    WORDS_PER_SECOND: float = 2.5
    MIN_SCENE_DURATION: float = 3.0   # seconds
    MAX_SCENE_DURATION: float = 15.0  # seconds

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Allow extra keys so we don't crash on unknown env vars
        extra = "ignore"

    def ensure_dirs(self) -> None:
        """Create required data directories on startup."""
        for d in [self.UPLOADS_DIR, self.OUTPUTS_DIR]:
            d.mkdir(parents=True, exist_ok=True)


# Single shared instance — import this everywhere
settings = Settings()
settings.ensure_dirs()
