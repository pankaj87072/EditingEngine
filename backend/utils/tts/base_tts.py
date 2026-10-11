"""
utils/tts/base_tts.py
---------------------
Abstract TTS provider interface. Providers implement synthesize(); they may also override
synthesize_scene() to honour per-scene delivery (emotion, energy, speed) and return word timings.
"""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from core.exceptions import TTSProviderError
from models.schema import ScriptScene, WordTiming


@dataclass
class SceneAudio:
    """Result of synthesising one scene."""
    duration: float
    word_timings: List[WordTiming] = field(default_factory=list)   # seconds from the START of this scene's file
    trim_end: Optional[float] = None                                # keep only this much of the file (None = all)


class BaseTTSProvider(ABC):
    provider_name: str = "BaseTTS"

    @classmethod
    def configured(cls) -> bool:
        """True if this provider can be used (credentials present)."""
        return True

    @abstractmethod
    def synthesize(
        self, text: str, output_path: str, *, language: Optional[str] = None, voice: Optional[str] = None, **kwargs,
    ) -> float:
        """Write speech for `text` to output_path and return its duration in seconds."""

    def synthesize_scene(
        self, scene: ScriptScene, output_path: str, *, prev_text: str = "", next_text: str = "",
        voice: Optional[str] = None, language: Optional[str] = None,
    ) -> SceneAudio:
        """Default: delivery-agnostic synthesis of the scene text."""
        return SceneAudio(duration=self.synthesize(scene.text, output_path, language=language, voice=voice))

    def fingerprint(self, scene: ScriptScene, prev_text: str = "", next_text: str = "") -> str:
        """Deterministic description of everything that changes the audio (used as the cache key)."""
        return f"{self.provider_name}|{scene.text}"

    def get_word_timings(self, text: str, audio_duration: float) -> List[WordTiming]:
        return []

    @staticmethod
    def audio_duration(path: str) -> float:
        """Exact duration via ffprobe. Raises if the file is not valid audio (so the caller can fall back)."""
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, timeout=15,
            )
            d = float(r.stdout.strip())
        except Exception as exc:
            raise TTSProviderError(f"Generated audio is not readable: {exc}") from exc
        if d < 0.05:
            raise TTSProviderError("Generated audio is empty.")
        return round(d, 3)
