"""
utils/tts/google_tts.py
-----------------------
Google Cloud Text-to-Speech provider.

Uses the google-cloud-texttospeech SDK.
Requires GOOGLE_APPLICATION_CREDENTIALS env var (service account JSON).

Falls back to gTTS (offline-friendly) if the Cloud SDK is unavailable,
so development works without a Google Cloud project.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

from core.config import settings
from core.exceptions import TTSProviderError
from core.logging import get_logger
from models.schema import WordTiming
from utils.tts.base_tts import BaseTTSProvider

logger = get_logger("GoogleTTSProvider")


class GoogleTTSProvider(BaseTTSProvider):
    provider_name = "google"

    def synthesize_scene(self, scene, output_path, *, prev_text="", next_text="", voice=None, language=None):
        """Google has no emotion control: map the scene's speed and (if a direction was given) energy to rate/pitch."""
        from utils.tts.base_tts import SceneAudio

        pitch = 0.0
        if scene.tts_energy is not None:
            pitch = max(-2.0, min(3.0, (scene.tts_energy - 0.5) * 5.0))
        return SceneAudio(duration=self.synthesize(scene.text, output_path, language=language, voice=voice,
                                                   speed=scene.speech_speed, pitch=pitch))

    def fingerprint(self, scene, prev_text="", next_text=""):
        return f"google|{settings.GOOGLE_TTS_LANGUAGE}|{settings.GOOGLE_TTS_VOICE}|{scene.speech_speed}|{scene.tts_energy}|{scene.text}"

    def synthesize(
        self,
        text: str,
        output_path: str,
        *,
        language: Optional[str] = None,
        voice: Optional[str] = None,
        speed: float = 1.0,
        pitch: float = 0.0,
        **kw,
    ) -> float:
        """
        Attempt Google Cloud TTS first; fall back to gTTS (free).
        Returns audio duration in seconds.
        """
        lang = language or settings.GOOGLE_TTS_LANGUAGE
        voice_name = voice or settings.GOOGLE_TTS_VOICE

        try:
            return self._synthesize_cloud(text, output_path, lang, voice_name, speed, pitch)
        except ImportError:
            logger.warning(
                "google-cloud-texttospeech not installed — falling back to gTTS."
            )
            return self._synthesize_gtts(text, output_path, lang, speed)
        except Exception as exc:
            logger.warning(f"Google Cloud TTS failed ({exc}) — falling back to gTTS.")
            return self._synthesize_gtts(text, output_path, lang, speed)

    # ── Google Cloud TTS ──────────────────────────────────────────────────────

    def _synthesize_cloud(
        self,
        text: str,
        output_path: str,
        language: str,
        voice_name: str,
        speed: float = 1.0,
        pitch: float = 0.0,
    ) -> float:
        from google.cloud import texttospeech  # type: ignore

        client = texttospeech.TextToSpeechClient()

        synthesis_input = texttospeech.SynthesisInput(text=text)

        voice_params = texttospeech.VoiceSelectionParams(
            language_code=language,
            name=voice_name,
        )

        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=max(0.8, min(1.25, 0.98 * speed)),
            pitch=pitch,
        )

        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice_params,
            audio_config=audio_config,
        )

        Path(output_path).write_bytes(response.audio_content)
        logger.info(f"Google Cloud TTS → {output_path}")
        return self._get_audio_duration(output_path)

    # ── gTTS fallback ─────────────────────────────────────────────────────────

    # region -> Google Translate TLD, which selects the accent gTTS uses
    _TLD = {"IN": "co.in", "GB": "co.uk", "AU": "com.au", "US": "com", "CA": "ca", "ZA": "co.za"}

    def _synthesize_gtts(self, text: str, output_path: str, language: str, speed: float = 1.0) -> float:
        try:
            from gtts import gTTS  # type: ignore
        except ImportError as exc:
            raise TTSProviderError(
                "Neither google-cloud-texttospeech nor gTTS is installed. Run: pip install gtts"
            ) from exc
        lang_short, _, region = language.partition("-")
        tts = gTTS(text=text, lang=lang_short, tld=self._TLD.get(region.upper(), "com"), slow=False)
        tts.save(output_path)
        if abs(speed - 1.0) >= 0.04:                      # gTTS has no rate control: adjust tempo (audio only, cheap)
            tmp = output_path + ".tempo.mp3"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", output_path, "-filter:a",
                            f"atempo={max(0.8, min(1.25, speed)):.3f}", tmp], capture_output=True, timeout=60)
            if Path(tmp).exists() and Path(tmp).stat().st_size > 0:
                Path(tmp).replace(output_path)
        logger.info(f"gTTS ({language}) → {output_path}")
        return self._get_audio_duration(output_path)

    def _get_audio_duration(self, path: str) -> float:
        return self.audio_duration(path)

    def get_word_timings(
        self, text: str, audio_duration: float
    ) -> List[WordTiming]:
        """
        Google Cloud TTS supports word timings via TIMEPOINT marks,
        but that requires SSML input. We return [] here and let
        SubtitleTimingAgent estimate evenly-spaced timings.
        """
        return []
