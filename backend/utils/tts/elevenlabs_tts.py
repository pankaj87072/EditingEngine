"""
utils/tts/elevenlabs_tts.py
---------------------------
ElevenLabs provider over plain HTTPS (no SDK needed).

* Uses the /with-timestamps endpoint, so subtitles get REAL character-level timing.
* Script directions ([Excited, energetic]) never reach the API as text. The scene's emotion /
  energy / speed are translated into voice settings (stability, style, speed). With
  ELEVENLABS_MODEL=eleven_v3 they become inline audio tags instead ([excited], [curious] ...).
* previous_text / next_text give the model sentence context so scenes sound like one performance.
* Retries 429 / 5xx / timeouts with backoff; auth and validation errors fail fast so the caller can
  fall back to Google immediately.
"""

from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional

from core.config import settings
from core.exceptions import TTSProviderError
from core.logging import get_logger
from models.schema import ScriptScene, WordTiming
from utils.tts.base_tts import BaseTTSProvider, SceneAudio

logger = get_logger("ElevenLabsTTSProvider")
API = "https://api.elevenlabs.io"

# v3 inline audio tags (only used with ELEVENLABS_MODEL=eleven_v3)
_V3_TAG = {
    "excited": "[excited]", "curious": "[curious]", "mysterious": "[mysterious]", "suspense": "[suspenseful]",
    "confident": "[confident]", "serious": "[serious]", "calm": "[calm]", "playful": "[playful]",
    "sad": "[sad]", "angry": "[angry]", "urgent": "[urgent]", "friendly": "[warmly]",
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class ElevenLabsTTSProvider(BaseTTSProvider):
    provider_name = "elevenlabs"

    @classmethod
    def configured(cls) -> bool:
        return bool(settings.ELEVENLABS_API_KEY)

    # ── Delivery -> API controls ──────────────────────────────────────────────

    @staticmethod
    def voice_settings_for(scene: Optional[ScriptScene]) -> dict:
        """Lower stability + higher style = more expressive. Neutral text keeps safe, steady defaults."""
        if scene is None or scene.tts_energy is None:
            return {"stability": 0.5, "similarity_boost": 0.8, "style": 0.15, "use_speaker_boost": True, "speed": 1.0}
        e = scene.tts_energy
        stability = 0.62 - 0.35 * e
        if scene.delivery in ("authoritative", "informative", "warning") or scene.emotion in ("calm", "serious", "confident"):
            stability += 0.10                      # steadier, more assured
        if scene.delivery in ("suspense", "whisper"):
            stability += 0.05
        style = 0.10 + 0.60 * e + (0.10 if scene.delivery == "punchy" else 0.0) + (0.10 if scene.emotion == "playful" else 0.0)
        return {
            "stability": round(_clamp(stability, 0.25, 0.70), 2),
            "similarity_boost": 0.8,
            "style": round(_clamp(style, 0.0, 0.70), 2),
            "use_speaker_boost": True,
            "speed": round(_clamp(scene.speech_speed, 0.8, 1.2), 3),
        }

    def _is_v3(self) -> bool:
        return settings.ELEVENLABS_MODEL.startswith("eleven_v3")

    def _payload(self, scene: Optional[ScriptScene], text: str, prev_text: str, next_text: str) -> dict:
        if self._is_v3():
            tag = _V3_TAG.get(scene.emotion, "") if scene else ""
            e = scene.tts_energy if scene and scene.tts_energy is not None else 0.5
            body = {"text": f"{tag} {text}".strip(), "model_id": settings.ELEVENLABS_MODEL,
                    "voice_settings": {"stability": 0.0 if e >= 0.7 else 0.5}}     # v3 only has Creative / Natural / Robust
            return body
        body = {"text": text, "model_id": settings.ELEVENLABS_MODEL, "voice_settings": self.voice_settings_for(scene)}
        if prev_text:
            body["previous_text"] = prev_text[-400:]
        if next_text:
            body["next_text"] = next_text[:400]
        return body

    def fingerprint(self, scene: ScriptScene, prev_text: str = "", next_text: str = "") -> str:
        return json.dumps([self.provider_name, settings.ELEVENLABS_VOICE_ID, self._payload(scene, scene.text, prev_text, next_text)],
                          sort_keys=True, ensure_ascii=False)

    # ── Public API ────────────────────────────────────────────────────────────

    def synthesize(self, text: str, output_path: str, *, language: Optional[str] = None, voice: Optional[str] = None, **kw) -> float:
        audio = self._request(None, text, "", "", output_path, voice)
        return audio.duration

    def synthesize_scene(self, scene, output_path, *, prev_text="", next_text="", voice=None, language=None) -> SceneAudio:
        return self._request(scene, scene.text, prev_text, next_text, output_path, voice)

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def _request(self, scene, text, prev_text, next_text, output_path, voice) -> SceneAudio:
        if not settings.ELEVENLABS_API_KEY:
            raise TTSProviderError("ELEVENLABS_API_KEY is not set.")
        voice_id = voice or settings.ELEVENLABS_VOICE_ID
        payload = self._payload(scene, text, prev_text, next_text)
        sent_text = payload["text"]
        url = f"{API}/v1/text-to-speech/{voice_id}/with-timestamps?output_format=mp3_44100_128"
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST", headers={
            "xi-api-key": settings.ELEVENLABS_API_KEY, "Content-Type": "application/json", "Accept": "application/json"})

        data = None
        for attempt in range(settings.ELEVENLABS_RETRIES + 1):
            try:
                with urllib.request.urlopen(req, timeout=settings.ELEVENLABS_TIMEOUT) as resp:
                    data = json.loads(resp.read().decode())
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:200] if hasattr(exc, "read") else ""
                if exc.code in (429, 500, 502, 503, 504) and attempt < settings.ELEVENLABS_RETRIES:
                    wait = float(exc.headers.get("Retry-After", 0) or 0) if exc.headers else 0.0
                    time.sleep(min(10.0, wait or 1.5 * 2 ** attempt))
                    continue
                raise TTSProviderError(f"ElevenLabs HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < settings.ELEVENLABS_RETRIES:
                    time.sleep(1.5 * 2 ** attempt)
                    continue
                raise TTSProviderError(f"ElevenLabs request failed: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise TTSProviderError("ElevenLabs returned an unreadable response.") from exc

        try:
            audio_bytes = base64.b64decode(data["audio_base64"])
        except Exception as exc:
            raise TTSProviderError("ElevenLabs response had no audio.") from exc
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(audio_bytes)
        duration = self.audio_duration(output_path)

        timings = self.words_from_alignment(data.get("alignment") or data.get("normalized_alignment"), text)
        trim = min(duration, timings[-1].end_time + 0.12) if timings else None
        logger.info(f"ElevenLabs TTS → {output_path} ({duration:.2f}s, {len(timings)} word timings)")
        return SceneAudio(duration=duration, word_timings=timings, trim_end=trim)

    # ── Alignment -> word timings ─────────────────────────────────────────────

    @staticmethod
    def words_from_alignment(alignment: Optional[dict], expected_text: str) -> List[WordTiming]:
        """
        Group character timings into words, skipping any inline [audio tags]. Returns [] unless the
        word count matches the script text exactly (the caller then estimates inside the scene).
        """
        try:
            chars = alignment["characters"]
            starts = alignment["character_start_times_seconds"]
            ends = alignment["character_end_times_seconds"]
        except (TypeError, KeyError):
            return []
        if not chars or not (len(chars) == len(starts) == len(ends)):
            return []
        words: List[WordTiming] = []
        cur, w_start, w_end, in_tag = "", None, None, False
        for ch, s, e in list(zip(chars, starts, ends)) + [(" ", None, None)]:
            if ch == "[":
                in_tag = True
            if in_tag:
                if ch == "]":
                    in_tag = False
                continue
            if ch.isspace():
                if cur:
                    words.append(WordTiming(word=cur, start_time=round(float(w_start), 3), end_time=round(float(w_end), 3)))
                cur, w_start, w_end = "", None, None
                continue
            if w_start is None:
                w_start = s
            cur += ch
            w_end = e
        return words if len(words) == len(expected_text.split()) else []
