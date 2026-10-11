"""
agents/editing_engine.py
------------------------
EditingEngine: the deterministic rule engine. It always produces a complete, usable
edit with NO AI. The optional AI planner (editing_plan_agent.py) only refines it.

For every script scene it
  1. splits the scene into one or more SHOTS (length from the editing style, cut points
     preferably on phrase boundaries),
  2. scores every candidate (clip, start) window with a weighted formula,
         score = semantic + relevance + motion_match + quality + duration_fit + variety
               + hook_bonus + continuity + boundary
               - repetition - boring - bad_crop - straddle
     (weights live in core/editing_rules.py),
  3. keeps per-clip usage history so footage is never needlessly repeated,
  4. chooses crop (subject-safe), motion preset, zoom, speed and join type from the style.

`retime_plan()` later fits shot lengths to the *real* narration (word timings when the
TTS provider gives them, otherwise a punctuation-weighted estimate).
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from agents.base_agent import BaseAgent
from agents.video_analyzer import choose_crop_x, find_duplicate_clips, window_stats
from core import editing_rules as R
from models.analysis import ClipAnalysis
from models.schema import AudioResult, EditingIntensity, SceneMappingResult, ScriptScene

GENERIC_NAME_WORDS = {
    "img", "clip", "video", "vid", "mov", "mp4", "dsc", "pxl", "screen", "recording", "final", "copy", "new",
    "untitled", "footage", "movie", "mvi", "mkv", "avi", "webm", "take", "raw",
}


# ══════════════════════════════════════════════════════════════════════════════
# Small helpers
# ══════════════════════════════════════════════════════════════════════════════

def name_tokens(path: str) -> List[str]:
    stem = Path(path).stem
    stem = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem)
    toks = [t.lower() for t in re.split(r"[^A-Za-z]+", stem) if len(t) >= 3]
    return [t for t in toks if t not in GENERIC_NAME_WORDS]


def _matches(a: str, b: str) -> bool:
    if a == b:
        return True
    return len(a) >= 4 and len(b) >= 4 and (a in b or b in a or a[:5] == b[:5])


def semantic_match(clip_path: str, a: ClipAnalysis, scene: ScriptScene) -> Tuple[float, str]:
    """0..1: how well the clip's name / vision tags match the scene vocabulary."""
    clip_toks = name_tokens(clip_path)
    if a.visual:
        clip_toks += [str(t).lower() for t in a.visual.get("tags", []) if isinstance(t, str)]
    if not clip_toks:
        return 0.5, ""                                        # nothing to go on: neutral
    scene_toks = {t for t in (scene.keywords + scene.important_words + scene.nouns + scene.verbs)}
    hits = sorted({c for c in clip_toks for s in scene_toks if _matches(c, s)})
    if hits:
        return min(1.0, 0.6 + 0.2 * len(hits)), f"name/tag match ({', '.join(hits[:3])})"
    return 0.3, ""


def visual_relevance(a: ClipAnalysis, scene: ScriptScene, st: dict) -> float:
    r = 0.5
    if a.visual:
        tags = {str(t).lower() for t in a.visual.get("tags", []) if isinstance(t, str)}
        tags.add(str(a.visual.get("shot_type", "")).lower())
        hits = sum(1 for v in scene.visual_intent if any(_matches(v, t) for t in tags if t))
        return min(1.0, r + 0.25 * hits)
    if scene.intent in ("people", "emotion") and a.faces:
        r += 0.4 * st["face"]
    if scene.intent in ("place", "result") and a.orientation == "landscape":
        r += 0.1
    return min(1.0, r)


def _overlap(ranges: List[Tuple[float, float]], s: float, e: float) -> float:
    d = max(1e-6, e - s)
    return min(1.0, sum(max(0.0, min(e, b) - max(s, a)) for a, b in ranges) / d)


def _fits_usable(a: ClipAnalysis, s: float, e: float) -> bool:
    return any(u0 - 0.05 <= s and e <= u1 + 0.05 for u0, u1 in a.usable_ranges)


def motion_allowed(mo: str, role: str, d: float, motion_norm: float, a: ClipAnalysis, has_emphasis: bool) -> bool:
    """Is this motion preset sensible for this shot? (shared by the engine and the AI validator)"""
    if mo not in R.MOTION_PRESETS:
        return False
    if d < 1.0 and mo != "static":
        return False
    if mo in ("pan_h", "pan_v") and (d < 1.8 or a.camera_motion in ("pan", "tilt")):
        return False
    if mo == "cinematic_drift" and d < 2.5:
        return False
    if mo == "punch" and not has_emphasis and role != "hook":
        return False
    if motion_norm >= 0.6 and mo in ("dynamic_push", "pan_h", "pan_v", "punch"):
        return False                                           # footage already moves: don't compound
    return True


# ══════════════════════════════════════════════════════════════════════════════
# Engine
# ══════════════════════════════════════════════════════════════════════════════

class EditingEngine(BaseAgent):
    agent_name = "EditingEngine"

    def _execute(  # type: ignore[override]
        self,
        *,
        scenes: List[ScriptScene],
        analyses: Dict[str, ClipAnalysis],
        clip_paths: List[str],
        style: str = R.DEFAULT_STYLE,
        intensity: EditingIntensity = EditingIntensity.BALANCED,
        transition_override: Optional[str] = None,
    ) -> List[SceneMappingResult]:
        rules = R.get_style(style)
        intens = R.INTENSITY[intensity.value]
        paths = [p for p in clip_paths if Path(p).exists()] or list(clip_paths)
        if not paths:
            raise ValueError("No clips to edit.")
        an = {p: analyses.get(p) or ClipAnalysis(clip_path=p, degraded=True) for p in paths}
        dup = find_duplicate_clips(an)

        used: Dict[str, List[Tuple[float, float]]] = {p: [] for p in paths}
        used_secs: Dict[str, float] = {p: 0.0 for p in paths}
        prev_clip: Optional[str] = None
        prev_end = 0.0
        plan: List[SceneMappingResult] = []

        for scene in scenes:
            words = scene.text.split()
            for k, (lo, hi, dur) in enumerate(self._split_scene(scene, rules, intens["shot_scale"])):
                text = " ".join(words[lo:hi])
                best, top = self._best_candidate(scene, k, dur, an, dup, used, used_secs, prev_clip, prev_end, rules)
                p, s, comps, score, stats, crop_x = best
                emph = [w for w in scene.important_words if re.search(rf"\b{re.escape(w)}\b", text.lower())]
                plan.append(SceneMappingResult(
                    scene_index=scene.scene_index, shot_index=k, word_range=[lo, hi],
                    clip_path=p, clip_duration=an[p].duration, scene_text=text,
                    start=round(s, 3), duration=round(dur, 3), crop=self._crop_label(crop_x), crop_x=crop_x,
                    caption_emphasis=emph[:3], scene_role=self._shot_role(scene, k), visual_energy=scene.energy,
                    subject_y=round(stats["sy"], 3) if (an[p].faces or stats["conc"] >= R.SUBJECT_CONFIDENT) else None,
                    planned_by="rules", why=self._explain(comps, score, len(top), p),
                    candidates=[{"clip": Path(c[0]).name, "start": round(c[1], 2), "score": round(c[3], 3)} for c in top],
                ))
                used[p].append((s, s + dur))
                used_secs[p] += dur
                prev_clip, prev_end = p, s + dur

        plan = self._apply_motion_speed(plan, an, rules, intens)
        plan = self._apply_joins(plan, rules, transition_override)
        self._store_meta("shots", len(plan))
        self._store_meta("style", rules.key)
        return plan

    # ── Shot splitting ────────────────────────────────────────────────────────

    @staticmethod
    def _split_scene(scene: ScriptScene, rules: R.StyleRules, scale: float) -> List[Tuple[int, int, float]]:
        words = scene.text.split()
        n_words = len(words)
        D = max(scene.estimated_duration, 0.5)
        lo_s, hi_s = rules.shot_min * scale, rules.shot_max * scale
        if scene.role == "hook":
            hi_s = min(hi_s, rules.hook_shot_max * scale)
        if scene.role == "cta":
            hi_s = min(hi_s, rules.cta_shot_max * scale)
        n = max(1, round(D / ((lo_s + hi_s) / 2)))
        n = max(n, math.ceil(D / hi_s - 1e-9))
        n = min(n, R.MAX_SHOTS_PER_SCENE, max(1, n_words // 2), max(1, int(D // R.MIN_SHOT)))
        if n == 1:
            return [(0, n_words, D)]
        ends = [i + 1 for i, w in enumerate(words[:-1]) if w[-1] in R.CAPTION_PAUSE_CHARS]
        cuts: List[int] = []
        for j in range(1, n):
            ideal = round(j * n_words / n)
            tol = max(1, int(0.3 * n_words / n))
            near = [e for e in ends if abs(e - ideal) <= tol and e > (cuts[-1] if cuts else 0)]
            c = min(near, key=lambda e: abs(e - ideal)) if near else ideal
            c = max(c, (cuts[-1] if cuts else 0) + 1)
            cuts.append(min(c, n_words - 1))
        bounds = [0] + cuts + [n_words]
        return [(bounds[i], bounds[i + 1], D * (bounds[i + 1] - bounds[i]) / n_words)
                for i in range(len(bounds) - 1) if bounds[i + 1] > bounds[i]]

    # ── Candidate scoring ─────────────────────────────────────────────────────

    def _best_candidate(self, scene, shot_idx, dur, an, dup, used, used_secs, prev_clip, prev_end, rules):
        W = lambda name: R.weight(rules, name)
        total_used = sum(used_secs.values())
        cands = []
        for ci, (p, a) in enumerate(an.items()):
            sem, sem_note = semantic_match(p, a, scene)
            for s in self._starts(a, dur):
                e = s + dur
                st = window_stats(a, s, min(dur, max(a.duration - s, 0.1)))
                crop_x, bad = choose_crop_x(a, st)
                fits = a.duration >= dur - 0.05
                comps = {
                    "semantic_match": sem,
                    "visual_relevance": visual_relevance(a, scene, st),
                    "motion_match": 1.0 - abs(min(1.0, st["motion"] * 8) - scene.energy),
                    "quality": st["quality"] * (0.7 if st["quality"] < R.LOW_QUALITY else 1.0),
                    "duration_fit": (1.0 if _fits_usable(a, s, e) else 0.7) if fits else R.LOOP_PENALTY_DURATION_FIT,
                    "variety": 0.6 * (p != prev_clip) + 0.4 * (1.0 - (used_secs[p] / total_used if total_used else 0.0)),
                    "hook_bonus": self._hook(scene, shot_idx, a, s, e, st),
                    "continuity_bonus": float(p == prev_clip and abs(s - prev_end) <= 0.6
                                              and not any(prev_end - 0.1 < c < s + 0.1 for c in a.scene_changes)),
                    "boundary_bonus": 0.5 * st["boundary_start"] + 0.5 * st["boundary_end"],
                }
                same = _overlap(used[p], s, e)
                dup_overlap = max([_overlap(used[q], s, e) for q in dup.get(p, [])] or [0.0])
                rep_inside = _overlap([tuple(r) for r in a.repeated_ranges], s, e)
                pens = {
                    "repetition_penalty": min(1.0, max(same, 0.8 * dup_overlap) + 0.4 * rep_inside),
                    "boring_penalty": st["boring"],
                    "bad_crop_penalty": bad,
                    "straddle_penalty": 1.0 if st["straddle"] else 0.0,
                }
                score = sum(W(k) * v for k, v in comps.items()) - sum(W(k) * v for k, v in pens.items())
                note = sem_note
                cands.append((p, s, {**comps, **{k: -v for k, v in pens.items()}, "_note": note}, score, st, crop_x, ci))
        cands.sort(key=lambda c: (-c[3], c[6], c[1]))
        top = [(c[0], c[1], c[2], c[3]) for c in cands[:3]]
        b = cands[0]
        return (b[0], b[1], b[2], b[3], b[4], b[5]), top

    @staticmethod
    def _shot_role(scene: ScriptScene, shot_idx: int) -> str:
        """Only the OPENING shot gets hook treatment; later shots of a hook scene are body."""
        return "body" if (scene.role == "hook" and shot_idx > 0) else scene.role

    @staticmethod
    def _hook(scene, shot_idx, a, s, e, st) -> float:
        if scene.role != "hook" or shot_idx != 0:
            return 0.0
        h = 0.5 * st["quality"] + 0.3 * min(1.0, st["motion"] * 8) + 0.2 * st["face"]
        if a.best_segments:
            b = a.best_segments[0]
            h += 0.25 * _overlap([(b["start"], b["end"])], s, e)
        if a.visual and isinstance(a.visual.get("hook_time"), (int, float)) and s <= a.visual["hook_time"] <= e:
            h += 0.25
        return min(1.0, h)

    @staticmethod
    def _starts(a: ClipAnalysis, dur: float) -> List[float]:
        room = a.duration - dur
        if room <= 0.05:
            return [0.0]
        grid = [round(i * R.SEGMENT_STEP, 2) for i in range(int(room / R.SEGMENT_STEP) + 1)]
        extra = [c for c in a.scene_changes if c <= room] + [c - dur for c in a.scene_changes if 0 <= c - dur <= room]
        extra += [u[0] for u in a.usable_ranges if u[0] <= room]
        out = sorted({round(x, 2) for x in grid + extra})
        if len(out) > 240:                                  # keep evaluation cost bounded
            out = out[:: math.ceil(len(out) / 240)]
        return out

    @staticmethod
    def _crop_label(crop_x: Optional[float]) -> str:
        if crop_x is None:
            return "center"
        return "left" if crop_x < 0.33 else "right" if crop_x > 0.66 else "center"

    @staticmethod
    def _explain(comps: dict, score: float, n_alts: int, clip: str) -> str:
        pos = sorted(((k, v) for k, v in comps.items() if not k.startswith("_") and v > 0 and not k.endswith("_penalty")),
                     key=lambda kv: -kv[1] * R.SCORE_WEIGHTS.get(kv[0], 0))[:3]
        neg = [k for k, v in comps.items() if k.endswith("_penalty") and v < -0.3]
        parts = [f"{k.replace('_', ' ')} {v:.2f}" for k, v in pos]
        s = f"Best of the candidates for this shot (score {score:.2f}): " + ", ".join(parts)
        if comps.get("_note"):
            s += f"; {comps['_note']}"
        if neg:
            s += f". Trade-offs: {', '.join(n.replace('_penalty', '') for n in neg)}"
        return s

    # ── Motion / speed ────────────────────────────────────────────────────────

    def _apply_motion_speed(self, plan, an, rules, intens):
        out: List[SceneMappingResult] = []
        prev_motion = ""
        for i, m in enumerate(plan):
            a = an[m.clip_path]
            d = m.duration or 1.0
            st = window_stats(a, m.start, min(d, max(a.duration - m.start, 0.1)))
            motion_norm = min(1.0, st["motion"] * 8)

            # speed: conservative; never distorts the voiceover (the video is retimed, not the audio)
            speed = 1.0
            if st["boring"] > 0.5 and m.scene_role not in ("hook", "cta") and rules.speed_boring > 1.0:
                speed = rules.speed_boring
            elif m.scene_role in ("hook", "payoff") and motion_norm >= 0.5 and rules.speed_important < 1.0:
                speed = rules.speed_important
            speed = R.clamp(speed, R.SPEED_MIN, R.SPEED_MAX)
            if m.start + d * speed > a.duration + 0.05:      # not enough footage for a speed-up
                speed = 1.0

            motion = self._choose_motion(rules, m.scene_role, i, d, motion_norm, a, prev_motion, bool(m.caption_emphasis))
            prev_motion = motion
            factor = {"static": 0.0, "push_in": 1.0, "pull_out": 1.0, "pan_h": 1.3, "pan_v": 1.3,
                      "dynamic_push": 1.6, "punch": 1.2, "cinematic_drift": 0.6}[motion]
            role_mult = {"hook": 1.2, "cta": 0.7}.get(m.scene_role, 1.0)
            zoom = 1.0 if motion == "static" else 1.0 + R.BASE_ZOOM * rules.motion_strength * intens["motion"] * factor * role_mult
            zoom = round(R.clamp(zoom, R.ZOOM_MIN, R.ZOOM_MAX), 3)

            punch_at = None
            if (rules.punch_on_emphasis or motion == "punch") and m.caption_emphasis and d >= 1.0:
                words = m.scene_text.lower().split()
                first = next((j for j, w in enumerate(words) if w.strip(".,!?;:\"'") in m.caption_emphasis), 0)
                punch_at = round(R.clamp(d * first / max(1, len(words)), 0.2, d - 0.4), 2)
            elif motion == "punch":
                punch_at = round(min(0.4, d * 0.2), 2)
            out.append(m.model_copy(update={
                "speed": round(speed, 3), "motion": motion, "zoom": zoom, "punch_at": punch_at,
                "effect": "punch" if punch_at is not None else "none",
            }))
        return out

    @staticmethod
    def _choose_motion(rules, role, i, d, motion_norm, a, prev, has_emphasis) -> str:
        pool = list(rules.motion_pool.get(role) or rules.motion_pool["body"])
        ok = [mo for mo in pool if motion_allowed(mo, role, d, motion_norm, a, has_emphasis)]
        if not ok:
            ok = ["static" if motion_norm >= 0.6 or d < 1.0 else "push_in"]
        if a.is_static and role == "body":                    # a locked-off shot benefits from movement
            ok = [m for m in ok if m != "static"] or ok
        rotated = ok[i % len(ok):] + ok[: i % len(ok)]
        return next((m for m in rotated if m != prev), rotated[0])

    # ── Joins between shots ───────────────────────────────────────────────────

    @staticmethod
    def _apply_joins(plan: List[SceneMappingResult], rules: R.StyleRules, override: Optional[str]) -> List[SceneMappingResult]:
        out: List[SceneMappingResult] = []
        since_accent = 99
        for i, m in enumerate(plan):
            if i == len(plan) - 1:
                out.append(m.model_copy(update={"join_after": "cut", "join_dur": 0.0}))
                continue
            nxt = plan[i + 1]
            same_scene = nxt.scene_index == m.scene_index
            kind, dur = (rules.inshot_join, rules.inshot_join_dur) if same_scene else (rules.scene_join, rules.scene_join_dur)
            if override is not None:
                kind, dur = {
                    "none": ("cut", 0.0),
                    "fade": ("cut" if same_scene else "dissolve", 0.0 if same_scene else 0.4),
                    "crossfade": ("dissolve", 0.5),
                    "zoom": ("cut" if same_scene else "zoomin", 0.0 if same_scene else 0.4),
                }.get(override, (kind, dur))
            elif (rules.accent_join and rules.accent_every and not same_scene
                  and m.scene_role != nxt.scene_role and since_accent >= rules.accent_every):
                kind, dur = rules.accent_join, 0.25
                since_accent = -1
            since_accent += 1
            if kind != "cut" and (m.duration or 0) < 3 * dur + 0.2:
                kind, dur = "cut", 0.0                         # shot too short to blend safely
            out.append(m.model_copy(update={"join_after": kind, "join_dur": dur if kind != "cut" else 0.0}))
        return out


# ══════════════════════════════════════════════════════════════════════════════
# Retiming to the real narration
# ══════════════════════════════════════════════════════════════════════════════

def word_start_times(scenes: List[ScriptScene], audio: AudioResult) -> List[float]:
    """Start time of every script word (+ final entry = audio end). Uses TTS word timings when usable."""
    words = [w for s in scenes for w in s.text.split()]
    n = len(words)
    wt = audio.word_timings
    if wt and n and abs(len(wt) - n) <= max(2, int(0.1 * n)):
        starts = [wt[min(len(wt) - 1, round(i * len(wt) / n))].start_time for i in range(n)]
        return [round(x, 3) for x in starts] + [audio.duration]
    weights = [1.0 + (0.6 if w[-1:] in ",;:" else 0.0) + (1.5 if w[-1:] in ".!?" else 0.0) for w in words]
    total = sum(weights) or 1.0
    t, out = 0.0, []
    for w in weights:
        out.append(round(t, 3))
        t += audio.duration * w / total
    return out + [audio.duration]


def retime_plan(plan: List[SceneMappingResult], scenes: List[ScriptScene], audio: AudioResult) -> List[SceneMappingResult]:
    """
    Make shot lengths follow the actual voiceover. Shot i is shown for the time its words are spoken,
    plus the overlap of the blend that follows it, so cuts land on the narration.
    """
    if not plan or audio.duration <= 0:
        return plan
    starts = word_start_times(scenes, audio)
    offsets: Dict[int, int] = {}
    acc = 0
    for s in scenes:
        offsets[s.scene_index] = acc
        acc += len(s.text.split())
    scene_words = {s.scene_index: len(s.text.split()) for s in scenes}

    out: List[SceneMappingResult] = []
    for i, m in enumerate(plan):
        base = offsets.get(m.scene_index, 0)
        lo, hi = (m.word_range or [0, scene_words.get(m.scene_index, 1)])
        # Fall back to proportional split if the plan has no word ranges (older plans)
        t0 = 0.0 if i == 0 else starts[min(base + lo, len(starts) - 1)]
        t1 = starts[min(base + hi, len(starts) - 1)]
        spoken = max(t1 - t0, R.MIN_SHOT)
        d = spoken + (m.join_dur if i < len(plan) - 1 else 0.15)   # tail pad on the last shot
        spd = m.speed or 1.0
        start = min(m.start, max(0.0, m.clip_duration - d * spd))
        out.append(m.model_copy(update={"duration": round(d, 3), "start": round(start, 3)}))
    return out


def visible_timeline(plan: List[SceneMappingResult]) -> List[Tuple[float, float]]:
    """(start, end) of what each shot shows on the final timeline (blends overlap)."""
    out, cursor = [], 0.0
    for m in plan:
        d = m.duration or 0.0
        out.append((cursor, cursor + d - m.join_dur))
        cursor += d - m.join_dur
    return out


def caption_zones(plan: List[SceneMappingResult], position: str) -> List[Tuple[float, float, int]]:
    """
    ASS \\an alignments (2 bottom, 5 middle, 8 top) per time range so captions move off the subject.
    Only shots with a trusted subject position (face or concentrated saliency) get an override.
    """
    if not R.CAPTION_AVOID_SUBJECT:
        return []
    default_an = {"bottom": 2, "center": 5, "upper": 8}.get(position, 2)
    zones = []
    for m, (t0, t1) in zip(plan, visible_timeline(plan)):
        if m.subject_y is None:
            continue
        an = default_an
        if default_an == 2 and m.subject_y >= R.CAPTION_SUBJECT_LOW:
            an = 8
        elif default_an == 8 and m.subject_y <= R.CAPTION_SUBJECT_HIGH:
            an = 2
        elif default_an == 5 and R.CAPTION_SUBJECT_HIGH < m.subject_y < R.CAPTION_SUBJECT_LOW:
            an = 2 if m.subject_y < 0.5 else 8
        if an != default_an:
            zones.append((t0, t1, an))
    return zones


def plan_to_json(plan: List[SceneMappingResult], style: str, extra: Optional[dict] = None) -> dict:
    """User-facing, explainable plan (GET /result/{id}/plan)."""
    rules = R.get_style(style)
    shots = []
    for m, (v0, v1) in zip(plan, visible_timeline(plan)):
        d = m.duration or m.clip_duration
        shots.append({
            "scene_index": m.scene_index, "shot_index": m.shot_index,
            "script_segment": m.scene_text, "scene_role": m.scene_role,
            "clip": Path(m.clip_path).name,
            "start": round(m.start, 2), "end": round(m.start + d * (m.speed or 1.0), 2), "duration": round(d, 2),
            "timeline_start": round(v0, 2), "timeline_end": round(v1, 2),
            "crop": m.crop, "crop_x": m.crop_x, "zoom": m.zoom, "speed": m.speed, "motion": m.motion,
            "effect": m.effect, "join_after": m.join_after,
            "transition": m.join_after,                     # kept for older UI versions
            "caption_emphasis": m.caption_emphasis, "visual_energy": m.visual_energy,
            "why": m.why, "alternatives": m.candidates, "planned_by": m.planned_by,
        })
    doc = {"editing_style": rules.key, "editing_style_label": rules.label, "scenes": shots}
    if extra:
        doc.update(extra)
    return doc
