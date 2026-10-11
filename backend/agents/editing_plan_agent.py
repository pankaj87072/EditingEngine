"""
agents/editing_plan_agent.py
----------------------------
EditingPlanAgent: the OPTIONAL AI layer that *refines* the deterministic plan.

  EditingEngine (rules)  ->  complete plan, always
  EditingPlanAgent (AI)  ->  one compact structured call, only if a key is configured
  validate_plan()        ->  clamps/repairs every field, with or without AI

The model never sees video. It receives script scenes (with deterministic role/intent/
energy), analysed clip metadata (quality, motion, usable ranges, best segments, cuts,
subject position, optional vision tags) and the engine's current choice plus the best
alternatives. It returns JSON decisions which are validated FIELD BY FIELD; anything
invalid keeps the deterministic value. If the whole call fails, the plan is returned
unchanged. Results are cached on disk by input hash.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from agents.base_agent import BaseAgent
from agents.editing_engine import _overlap, _fits_usable, motion_allowed
from agents.video_analyzer import choose_crop_x, crop_window_fraction, window_stats
from core import editing_rules as R
from core import llm
from core.config import settings
from models.analysis import ClipAnalysis
from models.schema import EditingIntensity, SceneMappingResult, ScriptScene

SYSTEM_PROMPT = """You are the editing planner of a short-form (Reels/TikTok/Shorts) video tool.
A deterministic engine already produced a complete edit. Your job is to IMPROVE it where you have
a good reason, never to rebuild it. You cannot see video: use the analysed metadata and tags.

Structure rules:
- HOOK shots: strongest available visual, quick engagement, stronger but controlled motion, no slow intro.
- BODY shots: visual variety, match clips to the meaning of the text, avoid repeating the same footage.
- CTA shots: clean and stable (static or very gentle motion), subject visible.
Other rules:
- Choose a clip + `start` inside that clip's `usable` ranges, preferably at/inside `best` segments; never reuse a section already used.
- Do not use the same clip in two consecutive shots when other clips exist.
- `motion` is one of: static, push_in, pull_out, pan_h, pan_v, dynamic_push, punch, cinematic_drift.
- `zoom` 1.00-1.25 (peak). `speed` 0.85-1.2 (stay near 1.0). `crop` left|center|right only for landscape clips and only if the subject stays inside.
- `effect` is none or punch (a zoom pop on an emphasis word). `emphasis`: 1-3 words copied verbatim from the shot text.
- Respect the editing style's pace; do not add effects without a reason.
Reply with ONLY compact JSON, no prose:
{"shots":[{"i":0,"clip":0,"start":0.0,"crop":"center","motion":"push_in","zoom":1.1,"speed":1.0,"effect":"none","emphasis":["word"]}]}
Include only shots you want to change or confirm. `i` = shot index, `clip` = clip index."""


class EditingPlanAgent(BaseAgent):
    agent_name = "EditingPlanAgent"

    @staticmethod
    def enabled(n_shots: int = 0) -> bool:
        return settings.PLANNER_ENABLED and llm.available() and n_shots <= settings.PLANNER_MAX_SHOTS

    def _execute(  # type: ignore[override]
        self,
        *,
        scenes: List[ScriptScene],
        plan: List[SceneMappingResult],
        analyses: Dict[str, ClipAnalysis],
        style: str = R.DEFAULT_STYLE,
        intensity: EditingIntensity = EditingIntensity.BALANCED,
    ) -> List[SceneMappingResult]:
        if not analyses or not self.enabled(len(plan)):
            return plan
        try:
            paths = list(analyses.keys())
            payload = self._payload(scenes, plan, analyses, paths, style, intensity)
            reply = self._ask(payload)
            merged = self.merge(plan, reply, analyses, paths)
            changed = sum(1 for a, b in zip(plan, merged) if a != b)
            self.logger.info(f"AI planner refined {changed}/{len(plan)} shots")
            self._store_meta("planner", "ai")
            return merged
        except Exception as exc:                              # any failure -> deterministic plan unchanged
            self.logger.warning(f"AI planner unavailable, using rules plan: {exc}")
            return plan

    # ── Compact context for the model ─────────────────────────────────────────

    @staticmethod
    def _payload(scenes, plan, analyses, paths, style, intensity) -> str:
        role_of = {s.scene_index: s for s in scenes}
        clips = []
        for i, p in enumerate(paths):
            a = analyses[p]
            v = a.visual or {}
            clips.append({
                "i": i, "name": Path(p).name, "dur": round(a.duration, 1), "orient": a.orientation,
                "q": round(a.quality_score, 2), "motion": round(min(1.0, a.motion_score * 8), 2),
                "camera": a.camera_motion, "tags": v.get("tags", []), "shot": v.get("shot_type"),
                "desc": str(v.get("description", ""))[:80],
                "usable": a.usable_ranges[:4], "best": [[b["start"], b["end"]] for b in a.best_segments[:2]],
                "cuts": a.scene_changes[:6], "subject_x": a.subject.get("x"), "faces": len(a.faces),
            })
        shots = []
        idx_by_name = {Path(p).name: i for i, p in enumerate(paths)}
        for i, m in enumerate(plan):
            sc = role_of.get(m.scene_index)
            shots.append({
                "i": i, "scene": m.scene_index, "role": m.scene_role, "text": m.scene_text, "dur": round(m.duration or 0, 1),
                "energy": m.visual_energy, "intent": sc.intent if sc else "generic",
                "cur": {"clip": paths.index(m.clip_path) if m.clip_path in paths else 0, "start": m.start, "motion": m.motion,
                        "zoom": m.zoom, "speed": m.speed, "emphasis": m.caption_emphasis},
                "alts": [{"clip": idx_by_name.get(c["clip"], 0), "start": c["start"], "score": c["score"]}
                         for c in m.candidates[1:3]],
            })
        return json.dumps({"style": style, "intensity": intensity.value, "clips": clips, "shots": shots},
                          ensure_ascii=False, separators=(",", ":"))

    def _ask(self, payload: str) -> dict:
        key = hashlib.sha256((settings.PLANNER_MODEL + SYSTEM_PROMPT + payload).encode()).hexdigest()[:24]
        cache = settings.DATA_DIR / "plan_cache" / f"{key}.json"
        if cache.exists():
            return json.loads(cache.read_text(encoding="utf-8"))
        reply = llm.extract_json(llm.call_messages(
            system=SYSTEM_PROMPT, content=payload, model=settings.PLANNER_MODEL,
            max_tokens=2500, timeout=settings.PLANNER_TIMEOUT))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(reply), encoding="utf-8")
        return reply

    # ── Field-by-field validation of the model's reply ───────────────────────

    def merge(
        self, plan: List[SceneMappingResult], reply: dict, analyses: Dict[str, ClipAnalysis], paths: List[str],
    ) -> List[SceneMappingResult]:
        by_i: Dict[int, dict] = {}
        for s in reply.get("shots", []) if isinstance(reply.get("shots"), list) else []:
            if isinstance(s, dict) and isinstance(s.get("i"), int) and not isinstance(s.get("i"), bool):
                by_i[s["i"]] = s

        out: List[SceneMappingResult] = []
        used: Dict[str, List[tuple]] = {p: [] for p in paths}
        for i, m in enumerate(plan):
            ai = by_i.get(i)
            new = self._merge_one(m, ai, out[-1] if out else None, analyses, paths, used) if ai else m
            out.append(new)
            used[new.clip_path].append((new.start, new.start + (new.duration or 0) * (new.speed or 1.0)))
        return out

    def _merge_one(self, m, ai, prev, analyses, paths, used) -> SceneMappingResult:
        upd: dict = {}
        notes: List[str] = []
        d = m.duration or 1.0
        num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)

        # clip + start (must be real, inside usable footage, not a repeat, not back-to-back)
        clip, start = m.clip_path, m.start
        ci = ai.get("clip")
        if isinstance(ci, int) and not isinstance(ci, bool) and 0 <= ci < len(paths):
            cand = paths[ci]
            a = analyses[cand]
            st_val = ai.get("start") if num(ai.get("start")) else (m.start if cand == m.clip_path else 0.0)
            s = R.clamp(float(st_val), 0.0, max(0.0, a.duration - d))
            reps = _overlap(used[cand], s, s + d)
            back_to_back = prev is not None and prev.clip_path == cand and len(paths) > 1
            if (cand, round(s, 2)) != (m.clip_path, round(m.start, 2)):
                if _fits_usable(a, s, s + d) and reps < 0.5 and not back_to_back:
                    clip, start = cand, round(s, 3)
                    notes.append("clip/segment")
        a = analyses[clip]
        moved = (clip, start) != (m.clip_path, m.start)
        st = window_stats(a, start, min(d, max(a.duration - start, 0.1)))
        if moved:
            crop_x, _ = choose_crop_x(a, st)
            upd.update({"clip_path": clip, "clip_duration": a.duration, "start": start, "crop_x": crop_x,
                        "crop": "center" if crop_x is None else ("left" if crop_x < .33 else "right" if crop_x > .66 else "center"),
                        "subject_y": round(st["sy"], 3) if (a.faces or st["conc"] >= R.SUBJECT_CONFIDENT) else None})

        # crop (landscape only, and only if the subject stays inside the window)
        crop = ai.get("crop")
        w = crop_window_fraction(a)
        if isinstance(crop, str) and crop in ("left", "center", "right") and w < 0.999:
            cx_frac = {"left": 0.0, "center": 0.5, "right": 1.0}[crop]
            center = w / 2 + cx_frac * (1 - w)
            sx = (a.visual or {}).get("subject_x")
            if sx is None and a.subject.get("x") is not None and (
                a.subject.get("source") == "face" or float(a.subject.get("confidence", 0)) >= R.SUBJECT_CONFIDENT * 0.5
            ):
                sx = a.subject["x"]                          # face, or a confident saliency estimate
            if sx is None or abs(float(sx) - center) <= w / 2 - 0.05:
                upd.update({"crop": crop, "crop_x": cx_frac})
                notes.append("crop")

        # motion / zoom / speed / effect
        motion = m.motion
        mo = ai.get("motion")
        mnorm = min(1.0, st["motion"] * 8)
        if isinstance(mo, str) and motion_allowed(mo, m.scene_role, d, mnorm, a, bool(m.caption_emphasis)):
            motion = mo
            upd["motion"] = mo
            notes.append("motion")
        zoom = m.zoom
        if num(ai.get("zoom")):
            zoom = round(R.clamp(float(ai["zoom"]), R.ZOOM_MIN, R.ZOOM_MAX), 3)
        if motion == "static":
            zoom = 1.0
        elif motion != "static" and zoom <= 1.0:
            zoom = max(zoom, 1.04)
        if zoom != m.zoom:
            upd["zoom"] = zoom
            notes.append("zoom")
        if num(ai.get("speed")):
            sp = R.clamp(float(ai["speed"]), R.SPEED_MIN, R.SPEED_MAX)
            if start + d * sp <= a.duration + 0.05 and abs(sp - m.speed) > 1e-3:
                upd["speed"] = round(sp, 3)
                notes.append("speed")

        # emphasis: words must literally occur in this shot's text
        emph = m.caption_emphasis
        words = ai.get("emphasis")
        if isinstance(words, list):
            text = m.scene_text.lower()
            ok = []
            for wd in words:
                wd = str(wd).strip().strip(".,!?;:\"'").lower()
                if wd and re.search(rf"\b{re.escape(wd)}\b", text) and wd not in ok:
                    ok.append(wd)
            if ok and ok[:3] != emph:
                emph = ok[:3]
                upd["caption_emphasis"] = emph
                notes.append("emphasis")
        eff = ai.get("effect")
        if isinstance(eff, str) and eff in R.EFFECT_PRESETS:
            if eff == "punch" and d >= 1.0:
                words_l = m.scene_text.lower().split()
                first = next((j for j, wd in enumerate(words_l) if wd.strip(".,!?;:\"'") in emph), 0)
                upd.update({"effect": "punch", "punch_at": round(R.clamp(d * first / max(1, len(words_l)), 0.2, max(0.2, d - 0.4)), 2)})
                notes.append("punch")
            elif eff == "none" and motion != "punch":
                upd.update({"effect": "none", "punch_at": None})

        if not notes:
            return m
        upd["planned_by"] = "ai"
        upd["why"] = (m.why + " | AI refined: " + ", ".join(notes))[:400]
        return m.model_copy(update=upd)


# ══════════════════════════════════════════════════════════════════════════════
# Plan-wide validation (runs with or without AI)
# ══════════════════════════════════════════════════════════════════════════════

def validate_plan(plan: List[SceneMappingResult], analyses: Dict[str, ClipAnalysis]) -> List[SceneMappingResult]:
    """
    Guarantee that every value handed to FFmpeg is valid. Repairs instead of failing:
    unknown clip -> first known clip, impossible timing -> clamped, bad enums -> safe defaults.
    """
    if not plan:
        return plan
    known = list(analyses.keys())
    out: List[SceneMappingResult] = []
    for m in plan:
        upd: dict = {}
        if m.clip_path not in analyses and known:
            upd["clip_path"] = known[0]
        a = analyses.get(upd.get("clip_path", m.clip_path))
        clip_len = a.duration if a else m.clip_duration
        d = max(R.MIN_SHOT, m.duration or m.clip_duration or R.MIN_SHOT)
        speed = R.clamp(m.speed or 1.0, R.SPEED_MIN, R.SPEED_MAX)
        motion = m.motion if m.motion in R.MOTION_PRESETS else "push_in"
        zoom = 1.0 if motion == "static" else R.clamp(m.zoom or 1.05, R.ZOOM_MIN, R.ZOOM_MAX)
        start = R.clamp(m.start, 0.0, max(0.0, clip_len - d * speed))
        upd.update({
            "duration": round(d, 3), "speed": round(speed, 3), "motion": motion, "zoom": round(zoom, 3),
            "start": round(start, 3), "clip_duration": clip_len,
            "crop": m.crop if m.crop in ("left", "center", "right") else "center",
            "crop_x": None if m.crop_x is None else round(R.clamp(m.crop_x, 0.0, 1.0), 4),
            "effect": m.effect if m.effect in R.EFFECT_PRESETS else "none",
            "join_after": m.join_after if m.join_after in (*R.JOIN_TYPES, "legacy") else "cut",
            "join_dur": R.clamp(m.join_dur, 0.0, 1.0),
        })
        if m.punch_at is not None:
            upd["punch_at"] = round(R.clamp(m.punch_at, 0.0, max(0.0, d - 0.3)), 2)
        out.append(m.model_copy(update=upd))
    return out
