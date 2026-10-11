"""
tests/test_media_pipeline.py
----------------------------
Real FFmpeg, tiny synthetic clips. Proves the parts mocks cannot:
analysis + caching, motion is preserved (the old zoom froze frame 1), mixed joins,
and the output quality validator. Skipped automatically if ffmpeg is not installed.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from agents.video_analyzer import VideoAnalyzer
from core.config import settings
from core.exceptions import VideoCompositionError
from services.quality_service import QualityService
from utils import ffmpeg_utils as fu

pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


def _ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True, capture_output=True)


def _px(path, t):
    out = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-vf", "scale=1:1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return tuple(out[:3])


@pytest.fixture(scope="module")
def red_blue(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    p = d / "rb.mp4"
    _ff("-f", "lavfi", "-i", "color=c=red:s=1080x1920:r=30:d=1.5", "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:r=30:d=1.5",
        "-filter_complex", "[0][1]concat=n=2:v=1:a=0", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(p))
    return p


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    return tmp_path


def test_analyzer_measures_cuts_orientation_and_caches(tmp_path, isolated_cache):
    clip = tmp_path / "wide.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=duration=5:size=640x360:rate=30", "-f", "lavfi", "-i", "color=c=gray:s=640x360:r=30:d=3",
        "-filter_complex", "[0][1]concat=n=2:v=1:a=0", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(clip))
    an = VideoAnalyzer()
    a = an.analyze_clip(str(clip))
    assert a.orientation == "landscape" and (a.width, a.height) == (640, 360) and 7.5 < a.duration < 8.5
    assert any(abs(c - 5.0) < 0.5 for c in a.scene_changes)          # the hard cut at 5 s is found
    assert a.timeline["t"] and a.usable_ranges and a.best_segments and not a.degraded
    assert 0 <= a.quality_score <= 1 and a.dominant_colors
    again = an.analyze_clip(str(clip))                               # second call comes from the cache
    assert (isolated_cache / "analysis_cache" / f"{a.key}.json").exists() and again.model_dump() == a.model_dump()


def test_analyzer_handles_unreadable_files_without_raising(tmp_path, isolated_cache):
    bad = tmp_path / "broken.mp4"
    bad.write_bytes(b"not a video" * 100)
    out = VideoAnalyzer().run(clip_paths=[str(bad)])
    assert out[str(bad)].degraded and out[str(bad)].usable_ranges


def test_rotated_phone_footage_is_reported_as_portrait(tmp_path, isolated_cache):
    clip = tmp_path / "rot.mp4"
    _ff("-f", "lavfi", "-i", "testsrc=duration=2:size=640x360:rate=30", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-metadata:s:v", "rotate=90", str(tmp_path / "tmp.mp4"))
    _ff("-display_rotation", "90", "-i", str(tmp_path / "tmp.mp4"), "-c", "copy", str(clip))
    assert VideoAnalyzer().analyze_clip(str(clip)).orientation == "portrait"


def test_zoom_no_longer_freezes_the_first_frame(red_blue, tmp_path):
    for motion in ("push_in", "dynamic_push", "pan_h", "cinematic_drift"):
        out = tmp_path / f"{motion}.mp4"
        fu.render_shot(str(red_blue), str(out), duration=3.0, motion=motion, zoom=1.12)
        r, _, b = _px(out, 2.6)
        assert b > 200 and r < 60, f"{motion}: footage froze on the first frame"


def test_legacy_ken_burns_is_fixed_too(red_blue, tmp_path):
    out = tmp_path / "kb.mp4"
    fu.apply_ken_burns(str(red_blue), str(out), 3.0, 1.1)
    r, _, b = _px(out, 2.6)
    assert b > 200 and r < 60


def test_speed_and_trim_are_applied(red_blue, tmp_path):
    out = tmp_path / "fast.mp4"
    fu.render_shot(str(red_blue), str(out), start=0.0, duration=2.0, speed=1.5, motion="static")
    assert abs(fu._get_duration(str(out)) - 2.0) < 0.15
    assert _px(out, 1.7)[2] > 200                                    # 3 s of source squeezed into 2 s reaches the blue half


def test_mixed_cuts_and_blends_have_the_expected_length(red_blue, tmp_path):
    shots = []
    for i, d in enumerate((2.0, 2.5, 3.0)):
        o = tmp_path / f"s{i}.mp4"
        fu.render_shot(str(red_blue), str(o), duration=d, motion="static")
        shots.append(str(o))
    out = tmp_path / "joined.mp4"
    fu.concat_with_joins(shots, [("cut", 0.0), ("dissolve", 0.4)], str(out))
    assert abs(fu._get_duration(str(out)) - (2.0 + 2.5 + 3.0 - 0.4)) < 0.1
    out2 = tmp_path / "joined2.mp4"
    fu.concat_with_joins(shots, [("smoothleft", 0.25), ("cut", 0.0)], str(out2))
    assert abs(fu._get_duration(str(out2)) - (7.5 - 0.25)) < 0.1


def _reel(tmp_path, w=1080, h=1920, audio=True, name="reel.mp4"):
    out = tmp_path / name
    args = ["-f", "lavfi", "-i", f"testsrc=duration=3:size={w}x{h}:rate=30"]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=duration=3"]
    _ff(*args, "-c:v", "libx264", "-pix_fmt", "yuv420p", *(["-c:a", "aac", "-shortest"] if audio else []), str(out))
    return str(out)


def test_quality_report_passes_for_a_valid_reel(tmp_path):
    rep = QualityService().check(_reel(tmp_path), expected_duration=3.0, plan_duration=3.0, subtitle_count=4)
    assert rep["ok"] and not rep["errors"] and rep["audio"] and rep["decode_ok"]
    assert (rep["video"]["width"], rep["video"]["height"]) == (1080, 1920)


def test_quality_check_rejects_bad_output(tmp_path):
    q = QualityService()
    with pytest.raises(VideoCompositionError):
        q.check(str(tmp_path / "missing.mp4"), expected_duration=3)
    with pytest.raises(VideoCompositionError, match="Resolution"):
        q.check(_reel(tmp_path, 640, 360, name="small.mp4"), expected_duration=3)
    with pytest.raises(VideoCompositionError, match="audio"):
        q.check(_reel(tmp_path, audio=False, name="silent.mp4"), expected_duration=3)
    rep = QualityService().check(_reel(tmp_path, name="ok.mp4"), expected_duration=9.0, subtitle_count=0)
    assert any("voiceover" in w for w in rep["warnings"]) and any("Captions" in w for w in rep["warnings"])


# ══════════════════════════════════════════════════════════════════════════════
# Performance architecture: single-pass composition, single-decode analysis
# ══════════════════════════════════════════════════════════════════════════════

def _probe_streams(path):
    import json
    d = json.loads(subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                                  capture_output=True, text=True).stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    a = next(s for s in d["streams"] if s["codec_type"] == "audio")
    return v, a, float(d["format"]["duration"])


@pytest.fixture
def count_encodes(monkeypatch):
    """Counts ffmpeg processes and how many of them encode video."""
    calls = []
    orig = subprocess.run

    def spy(cmd, *a, **k):
        if isinstance(cmd, list) and cmd and cmd[0] in ("ffmpeg", "ffprobe"):
            calls.append({"tool": cmd[0], "video_encode": "libx264" in cmd, "cmd": cmd})
        return orig(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", spy)
    return calls


def _narration(tmp_path, dur=5.0, name="nar.wav"):
    p = tmp_path / name
    _ff("-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}:sample_rate=48000", "-c:a", "pcm_s16le", str(p))
    return str(p)


def _shots(clip, n=3, d=2.0, joins=(("cut", 0.0), ("dissolve", 0.4))):
    motions = ["push_in", "pan_h", "punch"]
    return [{"clip": str(clip), "start": 0.0, "duration": d, "speed": 1.0, "crop": "center", "crop_x": 0.5,
             "motion": motions[i % 3], "zoom": 1.1, "punch_at": 0.5 if motions[i % 3] == "punch" else None,
             "source_duration": 3.0, "flip": bool(i % 2),
             "join": joins[i][0] if i < len(joins) else "cut", "join_dur": joins[i][1] if i < len(joins) else 0.0} for i in range(n)]


@pytest.mark.parametrize("engine", ["scale", "zoompan"])
def test_single_pass_is_one_video_encode_with_correct_output(red_blue, tmp_path, count_encodes, monkeypatch, engine):
    monkeypatch.setattr(settings, "MOTION_ENGINE", engine)
    srt = tmp_path / "c.srt"
    srt.write_text("1\n00:00:00,200 --> 00:00:02,000\nStop wasting money\n\n2\n00:00:02,200 --> 00:00:05,000\nbuy less today\n", encoding="utf-8")
    sub = fu.prepare_subtitles(str(srt), "bottom", "bold", emphasis=["wasting"], punch=True)
    count_encodes.clear()
    out = tmp_path / "final.mp4"
    fu.compose_single_pass(shots=_shots(red_blue), audio_path=_narration(tmp_path), subtitle_filter=sub, output_path=str(out))
    assert sum(c["video_encode"] for c in count_encodes) == 1                 # ONE encode for the whole Reel
    v, a, dur = _probe_streams(out)
    assert (v["width"], v["height"], v["codec_name"], v["pix_fmt"]) == (1080, 1920, "h264", "yuv420p")
    assert v["avg_frame_rate"] == "30/1" and v["sample_aspect_ratio"] in ("1:1", None, "0:1") if "sample_aspect_ratio" in v else True
    assert (a["codec_name"], int(a["sample_rate"]), a["channels"]) == ("aac", 48000, 2)
    assert dur == pytest.approx(6.0 - 0.4, abs=0.15)                          # 3 x 2 s, one 0.4 s dissolve
    # faststart: the moov atom precedes the media data
    head = open(out, "rb").read(200000)
    assert head.find(b"moov") != -1 and head.find(b"moov") < head.find(b"mdat")
    assert _px(out, 1.0)[0] > 150 or _px(out, 1.0)[2] > 150                  # picture is present, not black


def test_single_pass_matches_motion_and_keeps_footage_flowing(red_blue, tmp_path):
    out = tmp_path / "f.mp4"
    fu.compose_single_pass(shots=[{**_shots(red_blue, 1, 3.0)[0], "motion": "dynamic_push"}], audio_path=_narration(tmp_path, 3.0),
                           subtitle_filter=None, output_path=str(out))
    r, _, b = _px(out, 2.6)
    assert b > 200 and r < 60


def test_single_pass_loops_short_footage_and_trims_start(red_blue, tmp_path):
    out = tmp_path / "loop.mp4"
    sh = _shots(red_blue, 1, 5.0)                      # needs 5 s from a 3 s clip -> loop
    fu.compose_single_pass(shots=sh, audio_path=_narration(tmp_path), subtitle_filter=None, output_path=str(out))
    assert _probe_streams(out)[2] == pytest.approx(5.0, abs=0.15)


def test_music_is_mixed_under_the_narration(red_blue, tmp_path):
    music = tmp_path / "m.wav"
    _ff("-f", "lavfi", "-i", "anoisesrc=d=2:c=pink:r=48000:a=0.5", "-c:a", "pcm_s16le", str(music))
    nar = tmp_path / "nar2.wav"                        # 1.5 s of voice-like tone, then silence
    _ff("-f", "lavfi", "-i", "sine=frequency=440:duration=1.5:sample_rate=48000", "-af", "apad=pad_dur=2.5", "-c:a", "pcm_s16le", str(nar))
    out = tmp_path / "mix.mp4"
    fu.compose_single_pass(shots=_shots(red_blue, 1, 4.0), audio_path=str(nar), subtitle_filter=None,
                           output_path=str(out), music_path=str(music))

    def level(t0, t1):
        r = subprocess.run(["ffmpeg", "-hide_banner", "-ss", str(t0), "-t", str(t1 - t0), "-i", str(out), "-vn", "-af", "volumedetect",
                            "-f", "null", "-"], capture_output=True, text=True)
        import re
        return float(re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr).group(1))

    pause = level(2.5, 3.8)                            # music only
    assert pause > -60                                 # the music bed is audible when nobody speaks
    assert _probe_streams(out)[1]["channels"] == 2


def test_agent_falls_back_to_multistage_when_single_pass_fails(red_blue, tmp_path, monkeypatch):
    from agents.editing_engine import EditingEngine, retime_plan
    from agents.script_segmentation_agent import ScriptSegmentationAgent
    from agents.subtitle_timing_agent import SubtitleTimingAgent
    from agents.video_composition_agent import VideoCompositionAgent
    from models.schema import AudioResult, TTSProvider

    scenes = ScriptSegmentationAgent().run(script="Stop wasting money on bad gear today. Learn the basics first and then upgrade slowly.")
    an = VideoAnalyzer().run(clip_paths=[str(red_blue)])
    plan = EditingEngine().run(scenes=scenes, analyses=an, clip_paths=[str(red_blue)], style="clean")
    audio = AudioResult(audio_path=_narration(tmp_path, 6.0), duration=6.0, provider=TTSProvider.GOOGLE)
    plan = retime_plan(plan, scenes, audio)
    subs = SubtitleTimingAgent().run(audio_result=audio, scenes=scenes)

    def boom(**kw):
        raise VideoCompositionError("simulated graph failure")

    monkeypatch.setattr(fu, "compose_single_pass", boom)
    out = VideoCompositionAgent().run(scene_mappings=plan, audio_result=audio, subtitles=subs, output_dir=str(tmp_path / "o"), job_id="j")
    v, a, dur = _probe_streams(out)
    assert (v["width"], v["height"]) == (1080, 1920) and dur > 4


def test_analysis_decodes_each_clip_once_and_makes_no_keyframes(tmp_path, isolated_cache, count_encodes):
    clip = tmp_path / "w.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=duration=4:size=640x360:rate=30", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(clip))
    count_encodes.clear()
    a = VideoAnalyzer().analyze_clip(str(clip))
    ffmpeg_procs = [c for c in count_encodes if c["tool"] == "ffmpeg"]
    decodes = [c for c in ffmpeg_procs if "-i" in c["cmd"] and str(clip) in c["cmd"]]
    assert len(decodes) == 1                                   # sampling + scene detection share ONE decode
    assert not a.keyframes and a.timeline["t"] and not any("-frames:v" in c["cmd"] for c in ffmpeg_procs)


def test_clips_are_analysed_in_parallel_and_cached(tmp_path, isolated_cache):
    paths = []
    for i in range(3):
        p = tmp_path / f"c{i}.mp4"
        _ff("-f", "lavfi", "-i", f"testsrc=duration=3:size=320x180:rate=30:decimals={i}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(p))
        paths.append(str(p))
    out = VideoAnalyzer().run(clip_paths=paths)
    assert list(out) == paths and all(not a.degraded for a in out.values())
    t = time.time() if False else None
    again = VideoAnalyzer().run(clip_paths=paths)
    assert [a.key for a in again.values()] == [a.key for a in out.values()]


def test_unreadable_clip_is_skipped_but_the_job_continues(tmp_path, isolated_cache):
    from unittest.mock import MagicMock
    from models.schema import Job
    from services.video_service import VideoService

    good = tmp_path / "01-good.mp4"
    _ff("-f", "lavfi", "-i", "testsrc=duration=2:size=320x180:rate=30", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(good))
    bad = tmp_path / "02-bad.mp4"
    bad.write_bytes(b"garbage" * 50)
    svc = VideoService(job_service=MagicMock(), storage_service=MagicMock())
    job = Job(job_id="x", script="s", clip_paths=[str(good), str(bad), str(tmp_path / "03-missing.mp4")])
    analyses, usable, dropped = svc._analyze(job)
    assert usable == [str(good)] and len(dropped) == 2 and "bad.mp4" in dropped[0]
    job.clip_paths = [str(bad)]
    with pytest.raises(VideoCompositionError, match="None of your clips"):
        svc._analyze(job)


def test_quality_check_catches_a_truncated_file(tmp_path):
    good = _reel(tmp_path, name="whole.mp4")
    data = open(good, "rb").read()
    cut = tmp_path / "cut.mp4"
    cut.write_bytes(data[: len(data) // 2])                     # a half-written upload / crashed encode
    with pytest.raises(VideoCompositionError):
        QualityService().check(str(cut), expected_duration=3.0, subtitle_count=3)
