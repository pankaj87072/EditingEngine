"""
tests/test_audio_generation_agent.py
------------------------------------
Unit tests for AudioGenerationAgent (per-scene synthesis, one assembled narration track).
Providers are fakes: no real API calls are made. Fallback/cache/concurrency/timing are covered in
test_voice_pipeline.py; this file covers the agent's basic contract.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from agents.audio_generation_agent import AudioGenerationAgent
from core.config import settings
from core.exceptions import AudioGenerationError, TTSProviderError
from models.schema import ScriptScene, TTSProvider, WordTiming
from utils import tts as tts_factory
from utils.tts.base_tts import BaseTTSProvider, SceneAudio

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")

TEXTS = ["Welcome to the future of technology.", "Our product changes how you interact with the world.",
         "Experience innovation like never before."]


@pytest.fixture
def scenes():
    return [ScriptScene(scene_index=i, text=t, word_count=len(t.split()), estimated_duration=2.0) for i, t in enumerate(TEXTS)]


class Fake(BaseTTSProvider):
    provider_name = "google"
    seen: list = []
    fail = False
    timings = False

    def synthesize(self, text, output_path, **kw):
        dur = 1.0 + 0.1 * len(text.split())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=duration={dur}", "-c:a", "libmp3lame", output_path], check=True)
        return dur

    def synthesize_scene(self, sc, output_path, **kw):
        type(self).seen.append(sc.text)
        if type(self).fail:
            raise TTSProviderError("provider exploded")
        words = [WordTiming(word=w, start_time=i * 0.2, end_time=i * 0.2 + 0.15) for i, w in enumerate(sc.text.split())] if type(self).timings else []
        return SceneAudio(duration=self.synthesize(sc.text, output_path), word_timings=words)


@pytest.fixture(autouse=True)
def fake_provider(monkeypatch, tmp_path):
    Fake.seen, Fake.fail, Fake.timings = [], False, False
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setitem(tts_factory._PROVIDER_MAP, TTSProvider.GOOGLE, Fake)
    monkeypatch.setitem(tts_factory._PROVIDER_MAP, TTSProvider.ELEVENLABS, Fake)


def run(scenes, tmp_path, provider=TTSProvider.GOOGLE, job_id="job"):
    return AudioGenerationAgent().run(scenes=scenes, output_dir=str(tmp_path / "out"), tts_provider=provider, job_id=job_id)


def test_no_scenes_raises(tmp_path):
    with pytest.raises(AudioGenerationError, match="No scenes"):
        run([], tmp_path)


def test_every_scene_is_synthesised_with_its_own_text(scenes, tmp_path):
    run(scenes, tmp_path)
    assert sorted(Fake.seen) == sorted(TEXTS)


def test_result_is_one_narration_file_with_its_real_duration(scenes, tmp_path):
    r = run(scenes, tmp_path, job_id="unique-job-id-123")
    assert r.audio_path.endswith(".wav") and "unique-job-id-123" in r.audio_path
    expected = sum(1.0 + 0.1 * len(t.split()) for t in TEXTS) + 2 * settings.SCENE_GAP
    assert r.duration == pytest.approx(expected, abs=0.12)


def test_provider_timings_are_used_and_offset_into_the_full_track(scenes, tmp_path):
    Fake.timings = True
    r = run(scenes, tmp_path)
    assert r.timing_source == "provider" and len(r.word_timings) == sum(len(t.split()) for t in TEXTS)
    first_of_second = len(TEXTS[0].split())
    assert r.word_timings[first_of_second].start_time > r.word_timings[first_of_second - 1].end_time


def test_provider_is_reported_in_the_result(scenes, tmp_path):
    assert run(scenes, tmp_path, TTSProvider.ELEVENLABS).provider == TTSProvider.GOOGLE   # fake reports itself as "google"


def test_tts_failure_raises_audio_generation_error(scenes, tmp_path):
    Fake.fail = True
    with pytest.raises(AudioGenerationError):
        run(scenes, tmp_path)


def test_output_dir_created_if_missing(scenes, tmp_path):
    target = tmp_path / "deep" / "nested"
    r = AudioGenerationAgent().run(scenes=scenes, output_dir=str(target), tts_provider=TTSProvider.GOOGLE, job_id="j")
    assert target.exists() and r.audio_path.startswith(str(target))
