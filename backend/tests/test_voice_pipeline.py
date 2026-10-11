"""
tests/test_voice_pipeline.py
----------------------------
Script directions -> delivery metadata -> TTS controls, provider fallback, caching, concurrency,
and subtitle/audio timing. Network is mocked; ffmpeg is used only for the audio assembly tests.
"""

from __future__ import annotations

import base64
import io
import json
import shutil
import subprocess
import threading
import time
import urllib.error

import pytest

from agents.audio_generation_agent import AudioGenerationAgent
from agents.delivery import clean_spoken, parse_directive, split_directive_blocks
from agents.script_segmentation_agent import ScriptSegmentationAgent
from agents.subtitle_timing_agent import SubtitleTimingAgent
from core.config import settings
from core.exceptions import AudioGenerationError, TTSProviderError
from models.schema import ScriptScene, TTSProvider
from utils import tts as tts_factory
from utils.tts.base_tts import BaseTTSProvider, SceneAudio
from utils.tts.elevenlabs_tts import ElevenLabsTTSProvider
from utils.tts.google_tts import GoogleTTSProvider

BIKE = '''[Excited, energetic]
"Bhai… agar tum bike lover ho, toh ye fact tumhe zaroor pata hona chahiye!"

[Curious, slightly mysterious]
"Jab tum bike ko suddenly brake karte ho…"

[Build suspense, slower]
"toh bike ka weight… actually front wheel ki taraf shift hota hai."

[Confident, informative]
"Isi wajah se front brake, braking power ka bada part provide karta hai."

[Serious, warning tone]
"Lekin iska matlab ye bilkul nahi… ki rear brake ko ignore karo!"

[Calm, authoritative]
"Dono brakes ko properly aur smoothly use karna… safe riding ke liye important hai."

[Excited, punchy ending]
"Ye bike fact pata tha tumhe?"

[Playful, engaging]
"Comment mein YES likho… aur aise facts ke liye follow kar lo!"
'''
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def scene(text="Hello there friend", **kw) -> ScriptScene:
    return ScriptScene(scene_index=0, text=text, word_count=len(text.split()), estimated_duration=2.0, **kw)


# ── directions -> metadata ───────────────────────────────────────────────────

def test_directions_are_removed_from_text_and_become_metadata():
    scenes = ScriptSegmentationAgent().run(script=BIKE)
    assert len(scenes) == 8
    joined = " ".join(s.text for s in scenes)
    assert "[" not in joined and "Excited" not in joined and '"' not in joined
    assert scenes[0].text.startswith("Bhai… agar tum bike lover ho") and scenes[0].text.endswith("chahiye!")
    got = [(s.emotion, s.delivery) for s in scenes]
    assert got[0][0] == "excited" and got[0][1] == "punchy"
    assert got[1][0] == "curious" and got[2][0] == "suspense" and got[2][1] == "suspense"
    assert got[3] == ("confident", "informative") and got[4][0] == "serious" and got[4][1] == "warning"
    assert got[5][0] == "calm" and got[5][1] == "authoritative" and got[6][0] == "excited" and got[7][0] == "playful"


def test_speed_energy_and_pauses_follow_the_direction():
    s = ScriptSegmentationAgent().run(script=BIKE)
    assert s[0].speech_speed > 1.0 > s[2].speech_speed          # excited faster, "build suspense, slower" slower
    assert s[0].tts_energy > s[5].tts_energy                     # excited > calm
    assert s[2].pause_after >= 0.3 and s[0].pause_after == 0.0
    assert all(0.8 <= x.speech_speed <= 1.2 for x in s)


def test_hinglish_text_and_punctuation_are_preserved():
    blocks = split_directive_blocks(BIKE)
    assert blocks[2][1] == "toh bike ka weight… actually front wheel ki taraf shift hota hai."
    assert "…" in blocks[0][1] and "!" in blocks[0][1] and "ho, toh" in blocks[0][1]


def test_script_without_directions_is_unchanged():
    a = ScriptSegmentationAgent().run(script="This is a plain script with no directions at all. It has two sentences in it.")
    assert all(s.emotion == "neutral" and s.tts_energy is None and s.directive == "" for s in a)


def test_edge_cases():
    assert clean_spoken('  “Hello   world”  ') == "Hello world"
    assert split_directive_blocks("See reference [1] for details.") == [(None, "See reference [1] for details.")]
    inline = split_directive_blocks("Intro line. [Whisper] Secret line. [Excited] Loud line!")
    assert [b[1] for b in inline] == ["Intro line.", "Secret line.", "Loud line!"] and inline[0][0] is None
    assert parse_directive("totally unknown words")["emotion"] == "neutral"


def test_direction_energy_feeds_the_editing_energy():
    s = ScriptSegmentationAgent().run(script=BIKE)
    assert s[0].energy > s[5].energy                              # excited line edits harder than the calm one


# ── ElevenLabs: request building ─────────────────────────────────────────────

def test_emotion_changes_voice_settings_but_never_the_spoken_text():
    p = ElevenLabsTTSProvider()
    exc = scene("Bhai yeh suno!", emotion="excited", delivery="punchy", tts_energy=0.9, speech_speed=1.05)
    calm = scene("Ab shant raho.", emotion="calm", delivery="authoritative", tts_energy=0.3, speech_speed=0.95)
    plain = scene("Normal line here")
    a, b, c = (p.voice_settings_for(x) for x in (exc, calm, plain))
    assert a["stability"] < b["stability"] and a["style"] > b["style"] and a["speed"] > b["speed"]
    assert c["stability"] == 0.5 and c["speed"] == 1.0                      # no direction -> steady defaults
    for vs in (a, b, c):
        assert 0 <= vs["stability"] <= 1 and 0 <= vs["style"] <= 1 and 0.7 <= vs["speed"] <= 1.2
    payload = p._payload(exc, exc.text, "", "")
    assert payload["text"] == "Bhai yeh suno!" and "[" not in payload["text"]


def test_v3_model_uses_audio_tags_instead(monkeypatch):
    monkeypatch.setattr(settings, "ELEVENLABS_MODEL", "eleven_v3")
    p = ElevenLabsTTSProvider()
    body = p._payload(scene("Dekho!", emotion="excited", tts_energy=0.9), "Dekho!", "prev", "next")
    assert body["text"] == "[excited] Dekho!" and "previous_text" not in body


def test_neighbour_text_is_sent_for_continuity():
    body = ElevenLabsTTSProvider()._payload(scene("Middle."), "Middle.", "Before.", "After.")
    assert body["previous_text"] == "Before." and body["next_text"] == "After."


def _fake_response(text, dur_chars=0.05):
    chars = list(text)
    return {"audio_base64": base64.b64encode(b"ID3" + b"\0" * 400).decode(),
            "alignment": {"characters": chars, "character_start_times_seconds": [round(i * dur_chars, 3) for i in range(len(chars))],
                          "character_end_times_seconds": [round((i + 1) * dur_chars, 3) for i in range(len(chars))]}}


class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


@pytest.fixture
def el_env(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "k")
    monkeypatch.setattr(settings, "ELEVENLABS_RETRIES", 2)
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(BaseTTSProvider, "audio_duration", staticmethod(lambda path: 1.5))
    return tmp_path


def test_alignment_becomes_word_timings(el_env, monkeypatch):
    sent = {}

    def fake_open(req, timeout=None):
        sent["body"], sent["url"], sent["key"] = json.loads(req.data), req.full_url, req.get_header("Xi-api-key")
        return _Resp(json.dumps(_fake_response(sent["body"]["text"])).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    sc = scene("Bhai… yeh suno!", emotion="excited", tts_energy=0.9)
    out = ElevenLabsTTSProvider().synthesize_scene(sc, str(el_env / "a.mp3"))
    assert "with-timestamps" in sent["url"] and sent["key"] == "k"
    assert [w.word for w in out.word_timings] == ["Bhai…", "yeh", "suno!"]
    assert out.word_timings[0].start_time == 0.0 and out.word_timings[-1].end_time > out.word_timings[0].end_time
    assert out.trim_end is not None and out.trim_end <= out.duration


def test_audio_tags_are_not_counted_as_words():
    from utils.tts.elevenlabs_tts import ElevenLabsTTSProvider as E
    text = "[excited] Dekho yeh!"
    al = {"characters": list(text), "character_start_times_seconds": [i * .1 for i in range(len(text))],
          "character_end_times_seconds": [(i + 1) * .1 for i in range(len(text))]}
    assert [w.word for w in E.words_from_alignment(al, "Dekho yeh!")] == ["Dekho", "yeh!"]
    assert E.words_from_alignment(al, "Dekho yeh aur ek") == []         # count mismatch -> caller estimates instead
    assert E.words_from_alignment(None, "x") == [] and E.words_from_alignment({"characters": []}, "x") == []


def test_rate_limit_is_retried_but_bad_key_is_not(el_env, monkeypatch):
    calls = {"n": 0}

    def flaky(req, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError(req.full_url, 429, "rate", {"Retry-After": "0"}, io.BytesIO(b"slow down"))
        return _Resp(json.dumps(_fake_response(json.loads(req.data)["text"])).encode())

    monkeypatch.setattr("urllib.request.urlopen", flaky)
    ElevenLabsTTSProvider().synthesize_scene(scene("Hi there you"), str(el_env / "b.mp3"))
    assert calls["n"] == 3

    calls["n"] = 0

    def unauthorised(req, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b"invalid api key"))

    monkeypatch.setattr("urllib.request.urlopen", unauthorised)
    with pytest.raises(TTSProviderError, match="401"):
        ElevenLabsTTSProvider().synthesize_scene(scene("Hi there you"), str(el_env / "c.mp3"))
    assert calls["n"] == 1


def test_network_failure_raises_a_clean_error(el_env, monkeypatch):
    def down(req, timeout=None):
        raise urllib.error.URLError("no route")
    monkeypatch.setattr("urllib.request.urlopen", down)
    with pytest.raises(TTSProviderError, match="request failed"):
        ElevenLabsTTSProvider().synthesize_scene(scene("Hi there you"), str(el_env / "d.mp3"))


# ── provider selection ───────────────────────────────────────────────────────

def test_elevenlabs_preferred_only_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "")
    assert [p.provider_name for p in tts_factory.resolve_chain(TTSProvider.AUTO)] == ["google"]
    assert [p.provider_name for p in tts_factory.resolve_chain(TTSProvider.ELEVENLABS)] == ["google"]
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "k")
    assert [p.provider_name for p in tts_factory.resolve_chain(TTSProvider.AUTO)] == ["elevenlabs", "google"]
    assert [p.provider_name for p in tts_factory.resolve_chain(TTSProvider.ELEVENLABS)] == ["elevenlabs", "google"]
    assert [p.provider_name for p in tts_factory.resolve_chain(TTSProvider.GOOGLE)] == ["google"]


def test_google_uses_indian_accent_and_scene_speed(monkeypatch, tmp_path):
    seen = {}

    class FakeGTTS:
        def __init__(self, text, lang, tld, slow):
            seen.update(text=text, lang=lang, tld=tld)
        def save(self, path):
            open(path, "wb").write(b"ID3" + b"\0" * 200)

    import sys, types
    monkeypatch.setitem(sys.modules, "gtts", types.SimpleNamespace(gTTS=FakeGTTS))
    monkeypatch.setattr(BaseTTSProvider, "audio_duration", staticmethod(lambda p: 1.0))
    monkeypatch.setattr(GoogleTTSProvider, "_synthesize_cloud", lambda *a, **k: (_ for _ in ()).throw(ImportError()))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
    GoogleTTSProvider().synthesize("namaste dosto", str(tmp_path / "g.mp3"), language="en-IN")
    assert (seen["lang"], seen["tld"]) == ("en", "co.in")
    GoogleTTSProvider().synthesize("namaste", str(tmp_path / "h.mp3"), language="hi-IN")
    assert (seen["lang"], seen["tld"]) == ("hi", "co.in")


# ── audio agent: fallback, cache, concurrency, timing ────────────────────────

class FakeProvider(BaseTTSProvider):
    """Tone per scene. Class attributes let tests script failures and observe concurrency."""
    provider_name = "google"
    fail = False
    delay = 0.0
    calls: list = []
    active = 0
    peak = 0
    lock = threading.Lock()
    with_timings = False

    def synthesize(self, text, output_path, **kw):
        dur = max(0.6, len(text.split()) * 0.3)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=300:duration={dur}", "-c:a", "libmp3lame", output_path], check=True)
        return dur

    def synthesize_scene(self, sc, output_path, **kw):
        cls = type(self)
        with cls.lock:
            cls.active += 1
            cls.peak = max(cls.peak, cls.active)
            cls.calls.append(sc.text)
        try:
            time.sleep(cls.delay)
            if cls.fail:
                raise TTSProviderError(f"{self.provider_name} is down")
            dur = self.synthesize(sc.text, output_path)
            tim = []
            if cls.with_timings:
                from models.schema import WordTiming
                ws = sc.text.split()
                tim = [WordTiming(word=w, start_time=round(i * 0.3, 3), end_time=round(i * 0.3 + 0.25, 3)) for i, w in enumerate(ws)]
            return SceneAudio(duration=dur, word_timings=tim)
        finally:
            with cls.lock:
                cls.active -= 1


class FakeEleven(FakeProvider):
    provider_name = "elevenlabs"
    fail = False
    calls: list = []
    with_timings = True
    @classmethod
    def configured(cls): return True


@pytest.fixture
def voices(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "TTS_CACHE", True)
    FakeProvider.fail, FakeProvider.delay, FakeProvider.calls, FakeProvider.peak = False, 0.0, [], 0
    FakeEleven.fail, FakeEleven.calls = False, []
    monkeypatch.setitem(tts_factory._PROVIDER_MAP, TTSProvider.GOOGLE, FakeProvider)
    monkeypatch.setitem(tts_factory._PROVIDER_MAP, TTSProvider.ELEVENLABS, FakeEleven)
    return tmp_path


def _scenes():
    return ScriptSegmentationAgent().run(script=BIKE)


def _run(tmp, provider=TTSProvider.AUTO, scenes=None, job="j"):
    return AudioGenerationAgent().run(scenes=scenes or _scenes(), output_dir=str(tmp / "out"), tts_provider=provider, job_id=job)


@needs_ffmpeg
def test_preferred_voice_used_when_available(voices):
    r = _run(voices)
    assert r.provider == TTSProvider.ELEVENLABS and not r.fallback_used and r.timing_source == "provider"


@needs_ffmpeg
def test_falls_back_to_google_when_elevenlabs_fails(voices):
    FakeEleven.fail = True
    r = _run(voices)
    assert r.provider == TTSProvider.GOOGLE and r.fallback_used and r.duration > 3
    assert any("elevenlabs" in w for w in r.warnings)
    assert len(r.word_timings) == sum(len(s.text.split()) for s in _scenes())     # captions still fully timed


@needs_ffmpeg
def test_a_single_failing_scene_switches_the_whole_voice(voices):
    """One video must never mix two voices."""
    calls = {"n": 0}
    orig = FakeEleven.synthesize_scene

    def flaky(self, sc, path, **kw):
        calls["n"] += 1
        if calls["n"] == 4:
            raise TTSProviderError("rate limited")
        return orig(self, sc, path, **kw)

    FakeEleven.synthesize_scene = flaky
    try:
        r = _run(voices)
    finally:
        FakeEleven.synthesize_scene = orig
    assert r.provider == TTSProvider.GOOGLE and r.fallback_used


@needs_ffmpeg
def test_both_providers_failing_raises_a_clear_error(voices):
    FakeEleven.fail = FakeProvider.fail = True
    with pytest.raises(AudioGenerationError, match="Could not generate the voiceover"):
        _run(voices)


@needs_ffmpeg
def test_cache_means_no_second_api_call(voices):
    _run(voices, job="a")
    first = len(FakeEleven.calls)
    r = _run(voices, job="b")
    assert first == 8 and len(FakeEleven.calls) == first and r.duration > 3


@needs_ffmpeg
def test_concurrency_is_bounded(voices, monkeypatch):
    monkeypatch.setattr(settings, "TTS_MAX_CONCURRENCY", 3)
    FakeEleven.delay = 0.15
    FakeEleven.peak = 0
    _run(voices)
    assert 2 <= FakeEleven.peak <= 3
    monkeypatch.setattr(settings, "TTS_MAX_CONCURRENCY", 1)
    FakeEleven.peak = 0
    FakeEleven.calls = []
    for f in (voices / "tts_cache").glob("*"):
        f.unlink()
    _run(voices)
    assert FakeEleven.peak == 1


@needs_ffmpeg
def test_timings_are_absolute_and_line_up_with_the_assembled_audio(voices):
    FakeEleven.with_timings = False                       # force the in-scene estimate path as well
    try:
        r = _run(voices, provider=TTSProvider.GOOGLE)
    finally:
        FakeEleven.with_timings = True
    ts = r.word_timings
    assert all(a.start_time <= b.start_time for a, b in zip(ts, ts[1:]))
    assert ts[-1].end_time <= r.duration + 0.05 and r.timing_source == "scene-estimate"
    scenes = _scenes()
    ends, n = [], 0
    for s in scenes:                                       # a scene's words stay inside that scene's slice of the audio
        n += len(s.text.split())
        ends.append(ts[n - 1].end_time)
    assert all(a < b for a, b in zip(ends, ends[1:]))
    cards = SubtitleTimingAgent().run(audio_result=r, scenes=scenes)
    assert cards[0].start_time < 0.5 and cards[-1].end_time <= r.duration + 0.05
    assert all(len(c.text.split()) <= 4 for c in cards)
    assert "[" not in " ".join(c.text for c in cards)


@needs_ffmpeg
def test_requested_pauses_add_silence(voices):
    base = _scenes()
    paused = [s.model_copy(update={"pause_after": 0.0}) for s in base]
    long = [s.model_copy(update={"pause_after": 0.5}) for s in base]
    a = _run(voices, TTSProvider.GOOGLE, paused, "p1")
    b = _run(voices, TTSProvider.GOOGLE, long, "p2")
    assert b.duration - a.duration == pytest.approx(0.5 * (len(base) - 1), abs=0.15)


@needs_ffmpeg
def test_caption_cards_never_cross_a_scene_boundary(voices):
    """A deliberate pause between two directed lines must not land in the middle of one card."""
    scenes = _scenes()
    for with_timings in (True, False):
        FakeEleven.with_timings = with_timings
        provider = TTSProvider.AUTO if with_timings else TTSProvider.GOOGLE
        r = _run(voices, provider, scenes, f"cap{with_timings}")
        cards = SubtitleTimingAgent().run(audio_result=r, scenes=scenes)
        boundaries, acc = set(), 0
        for s in scenes:
            acc += len(s.text.split())
            boundaries.add(acc)
        n = 0
        for c in cards:
            n += len(c.text.split())
            # every scene boundary coincides with the end of a card
        reached = set()
        n = 0
        for c in cards:
            n += len(c.text.split())
            reached.add(n)
        assert boundaries <= reached, f"a card straddles a scene boundary (timings={with_timings})"
    FakeEleven.with_timings = True
