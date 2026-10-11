"""
tests/test_editing_engine.py
-----------------------------
The deterministic editing engine, the AI-plan validator, retiming and captions.
Pure logic: no ffmpeg, no network (see test_media_pipeline.py for real-FFmpeg tests).
"""

from __future__ import annotations

import json

import pytest

from agents import editing_plan_agent as epa
from agents.editing_engine import (
    EditingEngine, caption_zones, plan_to_json, retime_plan, visible_timeline, word_start_times,
)
from agents.script_profile import enrich_scenes
from agents.subtitle_timing_agent import SubtitleTimingAgent
from agents.video_analyzer import choose_crop_x, window_stats
from agents.vision_agent import VisionAgent
from core import editing_rules as R
from core.config import settings
from models.analysis import ClipAnalysis
from models.schema import AudioResult, EditingIntensity, ScriptScene, TTSProvider, WordTiming
from utils import ffmpeg_utils


# ── helpers ──────────────────────────────────────────────────────────────────

def make_analysis(name, dur=20.0, w=1920, h=1080, motion=0.04, sharp=0.6, bright=0.5, cuts=(), boring=(),
                  sx=0.5, sy=0.5, conc=0.6, visual=None):
    n = int(dur * 2)
    t = [i * 0.5 for i in range(n)]
    return ClipAnalysis(
        clip_path=name, key=name, duration=dur, width=w, height=h, fps=30,
        orientation="landscape" if w > h else "portrait", resolution=f"{w}x{h}",
        sharpness_score=sharp, brightness_score=bright, motion_score=motion, quality_score=0.7,
        scene_changes=list(cuts), usable_ranges=[[0.0, dur]], boring_ranges=[list(b) for b in boring],
        best_segments=[{"start": 2.0, "end": 4.0, "score": 0.8}], visual=visual,
        subject={"x": sx, "y": sy, "source": "saliency", "confidence": conc},
        timeline={"fps": [2.0], "t": t, "motion": [motion] * n, "sharp": [sharp] * n, "bright": [bright] * n,
                  "sx": [sx] * n, "sy": [sy] * n, "conc": [conc] * n},
        hashes=[f"{i:016x}" for i in range(n)],
    )


def make_scene(i, text, role="body", dur=None, **kw):
    words = text.split()
    return ScriptScene(scene_index=i, text=text, word_count=len(words), estimated_duration=dur or len(words) / 2.5,
                       keywords=[w.strip(".,!?").lower() for w in words if len(w) > 4], role=role, **kw)


SCRIPT = [
    make_scene(0, "Stop wasting money on bad cameras. Most creators buy the wrong gear first.", "hook", 5.0,
               important_words=["wasting", "cameras"], intent="problem", energy=0.9),
    make_scene(1, "Learn the basics before you spend anything on equipment, then upgrade slowly.", "body", 5.0, energy=0.5),
    make_scene(2, "Follow for more simple gear tips.", "cta", 2.5, energy=0.4),
]


def run_engine(analyses, scenes=SCRIPT, style="clean", intensity=EditingIntensity.BALANCED, override=None):
    return EditingEngine().run(scenes=scenes, analyses=analyses, clip_paths=list(analyses), style=style,
                               intensity=intensity, transition_override=override)


@pytest.fixture
def clips3():
    return {n: make_analysis(n) for n in ("a.mp4", "b.mp4", "c.mp4")}


# ── script profile ───────────────────────────────────────────────────────────

def test_script_profile_roles_intent_and_emphasis():
    from agents.script_segmentation_agent import ScriptSegmentationAgent
    scenes = ScriptSegmentationAgent().run(script=(
        "Stop wasting money on bad cameras. Most creators buy the wrong gear and then blame their editing skills every single time. "
        "The best camera is the one you already own, so learn the basics first. Finally, your videos will look better and cost less. "
        "Follow for more simple gear tips."))
    assert scenes[0].role == "hook" and scenes[-1].role == "cta"
    assert scenes[0].intent == "problem" and scenes[0].energy >= 0.8
    assert "wasting" in scenes[0].important_words and len(scenes[0].important_words) <= 3
    assert scenes[0].visual_intent                       # suggested visual vocabulary


def test_every_style_is_well_formed():
    for key, st in R.STYLES.items():
        assert st.key == key and st.shot_min < st.shot_max
        assert set(R.ROLES) <= set(st.motion_pool), key
        assert all(m in R.MOTION_PRESETS for pool in st.motion_pool.values() for m in pool)
        assert st.scene_join in R.JOIN_TYPES and (st.accent_join is None or st.accent_join in R.JOIN_TYPES)
    assert R.get_style("nonsense").key == R.DEFAULT_STYLE


# ── engine: always a complete, valid plan ────────────────────────────────────

@pytest.mark.parametrize("style", list(R.STYLES))
def test_engine_produces_valid_plan_for_every_style(clips3, style):
    plan = run_engine(clips3, style=style)
    assert plan and all(m.planned_by == "rules" for m in plan)
    assert {m.scene_index for m in plan} == {0, 1, 2}
    assert plan[-1].join_after == "cut"
    for m in plan:
        assert m.clip_path in clips3 and m.duration >= R.MIN_SHOT
        assert R.ZOOM_MIN <= m.zoom <= R.ZOOM_MAX and R.SPEED_MIN <= m.speed <= R.SPEED_MAX
        assert m.motion in R.MOTION_PRESETS and m.why and m.candidates


def test_engine_works_with_no_analysis_at_all():
    """Degraded/neutral analyses (e.g. analyzer disabled) must still give a usable edit."""
    an = {"x.mp4": ClipAnalysis(clip_path="x.mp4", degraded=True, duration=8.0, usable_ranges=[[0, 8.0]])}
    plan = run_engine(an)
    assert plan and all(m.clip_path == "x.mp4" for m in plan)


def test_style_controls_pacing(clips3):
    punchy = run_engine(clips3, style="social_punchy")
    cinematic = run_engine(clips3, style="cinematic")
    assert len(punchy) > len(cinematic)
    assert max(m.duration for m in cinematic) > max(m.duration for m in punchy)


def test_intensity_scales_motion(clips3):
    calm = run_engine(clips3, style="dynamic", intensity=EditingIntensity.CALM)
    dyn = run_engine(clips3, style="dynamic", intensity=EditingIntensity.DYNAMIC)
    assert max(m.zoom for m in dyn) > max(m.zoom for m in calm)
    assert len(dyn) >= len(calm)


def test_only_opening_shot_gets_hook_treatment(clips3):
    plan = run_engine(clips3, style="social_punchy")
    hook_shots = [m for m in plan if m.scene_role == "hook"]
    assert len(hook_shots) == 1 and plan[0].scene_role == "hook"


def test_cta_is_stable_not_flashy(clips3):
    plan = run_engine(clips3, style="social_punchy")
    cta = [m for m in plan if m.scene_role == "cta"]
    assert cta and all(m.motion in ("static", "push_in") for m in cta)
    assert all(m.zoom < plan[0].zoom for m in cta)


# ── clip choice quality ──────────────────────────────────────────────────────

def test_never_repeats_the_same_section_of_one_clip():
    an = {"only.mp4": make_analysis("only.mp4", dur=40.0)}
    plan = run_engine(an, style="social_punchy")
    spans = sorted((m.start, m.start + m.duration * m.speed) for m in plan)
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        assert s2 >= e1 - 0.6, f"overlap between {(s1, e1)} and {(s2, e2)}"


def test_avoids_back_to_back_same_clip(clips3):
    plan = run_engine(clips3, style="social_punchy")
    assert all(a.clip_path != b.clip_path for a, b in zip(plan, plan[1:]))


def test_filename_semantics_influence_choice():
    scene = make_scene(0, "Our kitchen is where the magic happens every morning.", "hook", 4.0,
                       important_words=["kitchen"], nouns=["kitchen", "magic"])
    an = {"IMG_0001.mp4": make_analysis("IMG_0001.mp4"), "kitchen-morning.mp4": make_analysis("kitchen-morning.mp4"),
          "garage.mp4": make_analysis("garage.mp4")}
    plan = run_engine(an, scenes=[scene])
    assert plan[0].clip_path == "kitchen-morning.mp4"
    assert "match" in plan[0].why


def test_avoids_boring_and_blurry_footage_when_alternatives_exist():
    boring = make_analysis("boring.mp4", motion=0.005, boring=[(0, 20)])
    lively = make_analysis("lively.mp4", motion=0.05)
    plan = run_engine({"boring.mp4": boring, "lively.mp4": lively}, scenes=[SCRIPT[1]])
    assert all(m.clip_path == "lively.mp4" or m.speed >= 1.0 for m in plan)
    assert plan[0].clip_path == "lively.mp4"


def test_windows_do_not_straddle_a_cut_when_avoidable():
    a = make_analysis("cut.mp4", dur=12.0, cuts=[6.0])
    plan = run_engine({"cut.mp4": a}, scenes=[make_scene(0, "A short scene about nothing at all really.", "body", 3.0)])
    s, e = plan[0].start, plan[0].start + plan[0].duration
    assert not (s + 0.3 < 6.0 < e - 0.3)


def test_footage_already_moving_does_not_get_extra_motion():
    fast = make_analysis("fast.mp4", motion=0.12)   # motion_norm = 0.96
    plan = run_engine({"fast.mp4": fast}, style="dynamic")
    assert all(m.motion in ("static", "push_in", "pull_out", "cinematic_drift") for m in plan)


def test_boring_footage_is_sped_up_slightly_but_within_limits():
    a = make_analysis("b.mp4", motion=0.004, boring=[(0, 20)])
    plan = run_engine({"b.mp4": a}, style="social_punchy", scenes=[SCRIPT[1]])
    assert any(m.speed > 1.0 for m in plan) and all(R.SPEED_MIN <= m.speed <= R.SPEED_MAX for m in plan)


# ── smart crop ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("subject_x", [0.15, 0.5, 0.85])
def test_crop_window_contains_the_subject(subject_x):
    a = make_analysis("w.mp4", sx=subject_x, conc=0.9)
    crop_x, bad = choose_crop_x(a, window_stats(a, 0, 3))
    w = 0.5625 * 1080 / 1920                                   # 9:16 window as a fraction of a 16:9 frame
    centre = w / 2 + crop_x * (1 - w)
    assert abs(centre - subject_x) <= w / 2 and 0 <= crop_x <= 1


def test_portrait_source_has_no_horizontal_crop_choice():
    a = make_analysis("p.mp4", w=1080, h=1920)
    assert choose_crop_x(a, window_stats(a, 0, 3))[0] is None


def test_face_position_beats_saliency_for_cropping():
    a = make_analysis("f.mp4", sx=0.2, conc=0.5)
    a.faces = [{"t": 1.0, "x": 0.8, "y": 0.4, "w": 0.1, "h": 0.1}]
    a.subject = {"x": 0.8, "y": 0.4, "source": "face", "confidence": 0.9}
    crop_x, _ = choose_crop_x(a, window_stats(a, 0, 3))
    assert crop_x > 0.7


# ── retiming to the real narration ───────────────────────────────────────────

def _audio(duration, timings=None):
    return AudioResult(audio_path="x.mp3", duration=duration, provider=TTSProvider.GOOGLE, word_timings=timings or [])


@pytest.mark.parametrize("style", ["clean", "cinematic", "social_punchy"])
def test_retime_matches_voiceover_length(clips3, style):
    plan = run_engine(clips3, style=style)
    out = retime_plan(plan, SCRIPT, _audio(14.0))
    visible_end = visible_timeline(out)[-1][1]
    assert 14.0 <= visible_end <= 14.0 + 0.3               # video is never shorter than the audio
    assert all(m.duration >= R.MIN_SHOT for m in out)


def test_retime_lands_cuts_on_word_timings(clips3):
    words = [w for s in SCRIPT for w in s.text.split()]
    step = 14.0 / len(words)
    wt = [WordTiming(word=w, start_time=round(i * step, 3), end_time=round((i + 1) * step - 0.02, 3)) for i, w in enumerate(words)]
    plan = run_engine(clips3, style="social_punchy")
    out = retime_plan(plan, SCRIPT, _audio(14.0, wt))
    starts = word_start_times(SCRIPT, _audio(14.0, wt))
    off = {0: 0, 1: len(SCRIPT[0].text.split()), 2: len(SCRIPT[0].text.split()) + len(SCRIPT[1].text.split())}
    for m, (v0, _) in list(zip(out, visible_timeline(out)))[1:]:
        assert abs(v0 - starts[off[m.scene_index] + m.word_range[0]]) < 0.3


def test_estimated_timing_pauses_at_sentence_ends():
    starts = word_start_times([make_scene(0, "One two three. Four five six.")], _audio(6.0))
    assert starts[3] - starts[2] > starts[2] - starts[1]    # the word before the full stop takes longer


# ── plan validation ──────────────────────────────────────────────────────────

def test_validate_plan_repairs_impossible_values(clips3):
    plan = run_engine(clips3)
    bad = plan[0].model_copy(update={
        "clip_path": "ghost.mp4", "zoom": 9.0, "speed": 7.0, "motion": "explode", "start": 999.0, "duration": -3.0,
        "crop": "diagonal", "crop_x": 4.2, "effect": "lasers", "join_after": "wipe-of-doom", "join_dur": 50, "punch_at": 99,
    })
    fixed = epa.validate_plan([bad], clips3)[0]
    assert fixed.clip_path in clips3 and R.ZOOM_MIN <= fixed.zoom <= R.ZOOM_MAX
    assert fixed.speed == R.SPEED_MAX and fixed.motion == "push_in" and fixed.crop == "center"
    assert fixed.duration >= R.MIN_SHOT and 0 <= fixed.crop_x <= 1 and fixed.effect == "none"
    assert fixed.join_after == "cut" and fixed.join_dur <= 1.0 and fixed.punch_at <= fixed.duration
    assert fixed.start <= max(0.0, clips3[fixed.clip_path].duration - fixed.duration * fixed.speed)


# ── AI planner: optional, validated, cached ──────────────────────────────────

@pytest.fixture
def ai_on(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(settings, "PLANNER_ENABLED", True)
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)


def _ai_run(plan, clips, reply, monkeypatch, calls=None):
    def fake(**kw):
        if calls is not None:
            calls.append(kw)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply)
    monkeypatch.setattr("core.llm.call_messages", fake)
    return epa.EditingPlanAgent().run(scenes=SCRIPT, plan=plan, analyses=clips, style="clean",
                                      intensity=EditingIntensity.BALANCED)


def test_no_api_key_returns_deterministic_plan_unchanged(clips3, monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    plan = run_engine(clips3)
    assert epa.EditingPlanAgent().run(scenes=SCRIPT, plan=plan, analyses=clips3, style="clean",
                                      intensity=EditingIntensity.BALANCED) == plan


@pytest.mark.parametrize("reply", [RuntimeError("timeout"), "not json at all", "[1,2,3]", {"shots": "nope"}, {}])
def test_ai_failure_or_garbage_falls_back_to_rules(clips3, ai_on, monkeypatch, reply):
    plan = run_engine(clips3)
    assert _ai_run(plan, clips3, reply, monkeypatch) == plan


def test_hostile_ai_reply_is_validated_field_by_field(clips3, ai_on, monkeypatch):
    plan = run_engine(clips3, style="cinematic")
    words = plan[1].scene_text.lower().split()
    reply = {"shots": [
        {"i": 0, "clip": 99, "start": -5, "motion": "explode", "zoom": 9, "speed": 5, "effect": "lasers", "crop": "right"},
        {"i": 1, "clip": 1, "start": 0, "motion": "pull_out", "zoom": 1.12, "speed": 1.0,
         "emphasis": [words[0].strip(".,!?"), "notinthetext"]},
        {"i": 500, "clip": 0}, "junk", {"i": "x"},
    ]}
    out = _ai_run(plan, clips3, reply, monkeypatch)
    # shot 0: bad clip / motion / effect / crop rejected; out-of-range numbers clamped to the limits
    assert out[0].clip_path == plan[0].clip_path and out[0].start == plan[0].start
    assert out[0].motion == plan[0].motion and out[0].effect == plan[0].effect and out[0].crop == plan[0].crop
    assert out[0].zoom == R.ZOOM_MAX and out[0].speed == R.SPEED_MAX
    # shot 1: valid fields accepted, invalid emphasis word dropped
    assert out[1].motion == "pull_out" and out[1].planned_by == "ai"
    assert "notinthetext" not in out[1].caption_emphasis
    assert all(R.ZOOM_MIN <= m.zoom <= R.ZOOM_MAX and R.SPEED_MIN <= m.speed <= R.SPEED_MAX for m in out)


def test_ai_cannot_reuse_a_section_or_repeat_a_clip(clips3, ai_on, monkeypatch):
    plan = run_engine(clips3, style="social_punchy")
    first = plan[0]
    idx = list(clips3).index(first.clip_path)
    reply = {"shots": [{"i": 1, "clip": idx, "start": first.start}]}       # exactly the footage shot 0 used
    out = _ai_run(plan, clips3, reply, monkeypatch)
    assert (out[1].clip_path, out[1].start) == (plan[1].clip_path, plan[1].start)


def test_ai_result_is_cached_one_call_per_reel(clips3, ai_on, monkeypatch):
    calls: list = []
    plan = run_engine(clips3)
    reply = {"shots": [{"i": 0, "motion": "static"}]}
    _ai_run(plan, clips3, reply, monkeypatch, calls)
    _ai_run(plan, clips3, reply, monkeypatch, calls)
    assert len(calls) == 1
    assert "images" not in json.dumps(calls[0]["content"]) and len(calls[0]["content"]) < 12000   # compact, no media


def test_ai_receives_analysed_metadata_not_just_filenames(clips3, ai_on, monkeypatch):
    calls: list = []
    clips3["a.mp4"].visual = {"tags": ["person", "office"], "shot_type": "close_up", "description": "woman at desk"}
    _ai_run(run_engine(clips3), clips3, {"shots": []}, monkeypatch, calls)
    payload = json.loads(calls[0]["content"])
    c0 = payload["clips"][0]
    assert {"q", "motion", "usable", "best", "cuts", "tags", "shot", "subject_x"} <= set(c0)
    assert c0["tags"] == ["person", "office"] and payload["shots"][0]["role"] == "hook"


def test_too_many_shots_skips_the_ai_call(clips3, ai_on, monkeypatch):
    monkeypatch.setattr(settings, "PLANNER_MAX_SHOTS", 2)
    calls: list = []
    plan = run_engine(clips3)
    assert _ai_run(plan, clips3, {"shots": []}, monkeypatch, calls) == plan and not calls


def test_vision_output_is_sanitised():
    out = VisionAgent.validate({"tags": ["person", "dragon", 7], "shot_type": "alien", "subject_x": 4,
                                "hook_time": 999, "caption_safe": "everywhere", "description": "x" * 500}, 10.0)
    assert out["tags"] == ["person"] and out["shot_type"] == "medium" and out["subject_x"] == 1.0
    assert out["hook_time"] == 10.0 and out["caption_safe"] == "none" and len(out["description"]) == 160


# ── joins ────────────────────────────────────────────────────────────────────

def test_legacy_transition_override_maps_to_joins(clips3):
    cut_all = run_engine(clips3, style="cinematic", override="none")
    assert all(m.join_after == "cut" for m in cut_all)
    cross = run_engine(clips3, style="clean", override="crossfade")
    assert any(m.join_after == "dissolve" for m in cross[:-1])


def test_blends_are_never_placed_after_very_short_shots(clips3):
    plan = run_engine(clips3, style="cinematic")
    assert all(m.join_dur == 0 or m.duration >= 3 * m.join_dur + 0.2 for m in plan)


# ── explainability ───────────────────────────────────────────────────────────

def test_plan_json_explains_every_shot(clips3):
    plan = retime_plan(run_engine(clips3, style="storytelling"), SCRIPT, _audio(14.0))
    doc = plan_to_json(plan, "storytelling", {"planner": "rules"})
    assert doc["editing_style"] == "storytelling" and doc["planner"] == "rules"
    need = {"script_segment", "scene_role", "clip", "start", "end", "why", "motion", "crop", "zoom", "speed",
            "caption_emphasis", "planned_by", "join_after", "alternatives", "timeline_start"}
    assert all(need <= set(s) for s in doc["scenes"])


# ── captions ─────────────────────────────────────────────────────────────────

def test_phrase_groups_break_on_punctuation():
    g = SubtitleTimingAgent.phrase_groups("Stop wasting money, buy less. Learn first and then upgrade slowly".split(), 4)
    texts = [" ".join("Stop wasting money, buy less. Learn first and then upgrade slowly".split()[i] for i in grp) for grp in g]
    assert texts[0] == "Stop wasting money," and texts[1] == "buy less." and all(len(x.split()) <= 4 for x in texts)


def test_captions_move_away_from_a_low_subject():
    m = run_engine({"a.mp4": make_analysis("a.mp4", sy=0.8, conc=0.9)}, scenes=[SCRIPT[1]])
    plan = retime_plan(m, [SCRIPT[1]], _audio(6.0))
    assert caption_zones(plan, "bottom") and all(z[2] == 8 for z in caption_zones(plan, "bottom"))
    assert not caption_zones(plan, "upper")                 # already clear of the subject


def test_emphasis_punch_and_zone_tags():
    ass = "[Events]\r\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Stop wasting money\r\n"
    out = ffmpeg_utils._emphasise_words(ffmpeg_utils._apply_zones(ass, [(0.5, 1.5, 8)]), ["wasting"], punch=True)
    assert "{\\an8}" in out and "\\t(0,120,\\fscx122" in out and "{\\b1\\c&H00D7FF&" in out
    plain = ffmpeg_utils._emphasise_words(ass, ["wasting"], punch=False)
    assert "\\t(" not in plain and "wasting" in plain


def test_motion_filter_is_valid_and_keeps_frames_flowing():
    for mo in R.MOTION_PRESETS:
        f = ffmpeg_utils.motion_filter(mo, 1.12, 3.0, punch_at=1.0 if mo == "punch" else None)
        assert (f is None) == (mo == "static")
        if f:
            assert ":d=1:" in f and f"s={settings.VIDEO_WIDTH}x{settings.VIDEO_HEIGHT}" in f


def test_duplicate_clips_are_detected_and_penalised():
    from agents.video_analyzer import find_duplicate_clips
    a, b, c = make_analysis("a.mp4"), make_analysis("b.mp4"), make_analysis("c.mp4")
    c.hashes = [f"{(0xFFFFFFFFFFFFFFFF ^ i):016x}" for i in range(len(c.hashes))]       # visually different footage
    dup = find_duplicate_clips({"a.mp4": a, "b.mp4": b, "c.mp4": c})
    assert dup["a.mp4"] == ["b.mp4"] and dup["c.mp4"] == []
