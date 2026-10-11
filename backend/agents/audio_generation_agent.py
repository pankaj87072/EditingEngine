"""
agents/audio_generation_agent.py
--------------------------------
AudioGenerationAgent
--------------------
Responsibility: turn scenes into ONE narration track plus word-level timings.

  * Every scene is synthesised on its own so its delivery metadata (emotion, energy, speed) can steer
    the voice, and so we know each scene's exact length. Up to TTS_MAX_CONCURRENCY run in parallel.
  * Results are cached on disk by a deterministic key (provider, voice, settings, text, neighbours),
    so re-running a job or re-using a line costs no API call.
  * Providers are tried in order (ElevenLabs when configured, then Google). If the preferred voice
    fails for ANY scene the whole narration is regenerated with the next provider, so one video never
    mixes two voices.
  * Word timings come from the provider when it supplies them (ElevenLabs alignment). Otherwise they
    are estimated INSIDE each scene's exact duration, which keeps captions locked to the audio.

Input kwargs: scenes, output_dir, tts_provider, job_id.   Returns: AudioResult
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Tuple

from agents.base_agent import BaseAgent
from core.config import settings
from core.exceptions import AudioGenerationError
from models.schema import AudioResult, ScriptScene, TTSProvider, WordTiming
from utils import ffmpeg_utils
from utils.tts import resolve_chain
from utils.tts.base_tts import BaseTTSProvider, SceneAudio


class AudioGenerationAgent(BaseAgent):
    agent_name = "AudioGenerationAgent"

    def _execute(  # type: ignore[override]
        self, *, scenes: List[ScriptScene], output_dir: str, tts_provider: TTSProvider, job_id: str,
    ) -> AudioResult:
        if not scenes:
            raise AudioGenerationError("No scenes provided to AudioGenerationAgent.")
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        chain = resolve_chain(tts_provider)
        problems: List[str] = []
        for idx, provider in enumerate(chain):
            try:
                self._log_step(f"TTS provider: {provider.provider_name} ({len(scenes)} scenes)")
                result = self._run_provider(provider, scenes, output_dir, job_id)
                result.fallback_used = idx > 0
                result.warnings = problems
                if idx > 0:
                    self._log_step(f"Used fallback voice '{provider.provider_name}'")
                return result
            except Exception as exc:
                msg = f"{provider.provider_name}: {exc}"
                problems.append(msg)
                self.logger.warning(f"Voice provider failed, trying next ({msg})")
        raise AudioGenerationError("Could not generate the voiceover. " + " | ".join(problems))

    # ── One provider, all scenes ──────────────────────────────────────────────

    def _run_provider(self, provider: BaseTTSProvider, scenes, output_dir: str, job_id: str) -> AudioResult:
        n = len(scenes)
        files: List[Optional[Tuple[str, SceneAudio]]] = [None] * n
        workers = max(1, min(settings.TTS_MAX_CONCURRENCY, n))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._synth_one, provider, scenes, i, output_dir): i for i in range(n)}
            try:
                for fut in as_completed(futures):
                    files[futures[fut]] = fut.result()
            except Exception:
                for f in futures:
                    f.cancel()                       # stop queued work; this provider is abandoned
                raise

        # Gaps: a small natural gap plus any requested pauses.
        items, effective, gaps = [], [], []
        for i, sc in enumerate(scenes):
            path, audio = files[i]  # type: ignore[misc]
            eff = round(min(audio.duration, audio.trim_end or audio.duration), 3)
            gap = 0.0 if i == n - 1 else settings.SCENE_GAP + sc.pause_after + scenes[i + 1].pause_before
            items.append((path, audio.trim_end, gap))
            effective.append(eff)
            gaps.append(gap)
        out_path = str(Path(output_dir) / f"{job_id}_narration.wav")
        try:
            total = ffmpeg_utils.assemble_narration(items, out_path)
        except Exception as exc:
            raise AudioGenerationError(f"Could not assemble the narration: {exc}") from exc

        timings: List[WordTiming] = []
        sources = set()
        offset = 0.0
        for i, sc in enumerate(scenes):
            audio = files[i][1]  # type: ignore[index]
            if audio.word_timings:
                sources.add("provider")
                timings += [WordTiming(word=w.word, start_time=round(offset + w.start_time, 3),
                                       end_time=round(offset + min(w.end_time, effective[i]), 3)) for w in audio.word_timings]
            else:
                sources.add("scene-estimate")
                timings += self._estimate_words(sc.text, offset, effective[i])
            offset += effective[i] + gaps[i]

        try:
            enum_name = TTSProvider(provider.provider_name)
        except ValueError:
            enum_name = TTSProvider.GOOGLE
        self._store_meta("audio_path", out_path)
        self._store_meta("duration", total)
        return AudioResult(
            audio_path=out_path, duration=total, provider=enum_name, word_timings=timings,
            timing_source=sources.pop() if len(sources) == 1 else "mixed",
        )

    # ── One scene (cache aware) ───────────────────────────────────────────────

    def _synth_one(self, provider: BaseTTSProvider, scenes, i: int, output_dir: str) -> Tuple[str, SceneAudio]:
        sc = scenes[i]
        prev_text = scenes[i - 1].text if i > 0 else ""
        next_text = scenes[i + 1].text if i < len(scenes) - 1 else ""
        key = hashlib.sha256(provider.fingerprint(sc, prev_text, next_text).encode()).hexdigest()[:32]
        base = (settings.DATA_DIR / "tts_cache") if settings.TTS_CACHE else (Path(output_dir) / "tts_scenes")
        base.mkdir(parents=True, exist_ok=True)
        audio_file, meta_file = base / f"{key}.mp3", base / f"{key}.json"

        if settings.TTS_CACHE and audio_file.exists() and meta_file.exists():
            try:
                m = json.loads(meta_file.read_text(encoding="utf-8"))
                self.logger.info(f"TTS cache hit: scene {i}")
                return str(audio_file), SceneAudio(
                    duration=m["duration"], trim_end=m.get("trim_end"),
                    word_timings=[WordTiming(**w) for w in m.get("words", [])])
            except Exception:
                pass                                   # unreadable cache entry -> regenerate

        tmp = base / f"{key}.{i}.part.mp3"
        audio = provider.synthesize_scene(sc, str(tmp), prev_text=prev_text, next_text=next_text)
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise AudioGenerationError(f"Scene {i}: provider returned no audio.")
        shutil.move(str(tmp), audio_file)
        meta_file.write_text(json.dumps({
            "duration": audio.duration, "trim_end": audio.trim_end,
            "words": [w.model_dump() for w in audio.word_timings]}), encoding="utf-8")
        return str(audio_file), audio

    # ── Timing estimate inside a scene whose exact length is known ───────────

    @staticmethod
    def _estimate_words(text: str, start: float, duration: float) -> List[WordTiming]:
        words = text.split()
        if not words:
            return []
        weights = [max(2, len(re.sub(r"\W", "", w))) + (5 if w[-1:] in ",;:…" else 0) + (9 if w[-1:] in ".!?" else 0) for w in words]
        total = float(sum(weights))
        out, t = [], start
        for w, wt in zip(words, weights):
            d = duration * wt / total
            out.append(WordTiming(word=w, start_time=round(t, 3), end_time=round(t + d * 0.92, 3)))
            t += d
        return out
