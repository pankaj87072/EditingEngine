"""
agents/video_analyzer.py
------------------------
VideoAnalyzer: deterministic, cached analysis of every uploaded clip.

Nothing here calls an AI. It uses ffprobe + FFmpeg to decode a *small number of
low-resolution sampled frames* (never every frame) and computes simple, explainable
metrics in pure Python (no numpy/OpenCV required):

  duration / orientation (rotation aware) / fps / codec
  brightness, contrast, saturation, sharpness, dominant colours
  motion per sample, camera-motion estimate, static vs moving
  scene cuts (FFmpeg `scene` score; falls back to sampled-frame jumps)
  usable / boring / repeated ranges and the best-looking segments
  where the subject probably is (saliency; faces too when OpenCV is installed)
  a few keyframe JPEGs (used only if the optional vision model is enabled)

Results are cached in data/analysis_cache/<content-hash>.json, so re-uploading or
re-rendering the same clip never re-analyses it.

Every optional dependency degrades gracefully: if probing or sampling fails the clip
gets a neutral `degraded=True` analysis and the edit still completes.
"""

from __future__ import annotations

import bisect
import hashlib
import os
import json
import math
import re
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from agents.base_agent import BaseAgent
from core import editing_rules as R
from core.config import settings
from models.analysis import ANALYZER_VERSION, ClipAnalysis

GRID = 96            # sampled frames are scaled to GRID x GRID (aspect ignored on purpose)
WINDOW = 2.0         # seconds, for "best segment" scoring


# ══════════════════════════════════════════════════════════════════════════════
# Pure helpers (also used by the EditingEngine)
# ══════════════════════════════════════════════════════════════════════════════

def exposure_ok(b: float) -> float:
    """1.0 at mid-grey, falling toward 0 for very dark/bright frames."""
    return max(0.0, 1.0 - 1.6 * abs(b - 0.5))


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def window_stats(a: ClipAnalysis, start: float, dur: float) -> dict:
    """Aggregate the sampled timeline over [start, start+dur)."""
    tl = a.timeline
    ts = tl.get("t", [])
    idx = list(range(bisect.bisect_left(ts, start - 1e-6), bisect.bisect_left(ts, start + dur)))
    if not idx and ts:                                    # window narrower than sample spacing
        idx = [min(range(len(ts)), key=lambda i: abs(ts[i] - (start + dur / 2)))]

    def mean(key: str, default: float) -> float:
        arr = tl.get(key, [])
        vals = [arr[i] for i in idx if i < len(arr)]
        return sum(vals) / len(vals) if vals else default

    sharp, bright = mean("sharp", a.sharpness_score), mean("bright", a.brightness_score)
    motion = mean("motion", a.motion_score)
    sx, sy = mean("sx", 0.5), mean("sy", 0.5)
    sxs = [tl["sx"][i] for i in idx if i < len(tl.get("sx", []))]
    spread = (max(sxs) - min(sxs)) if sxs else 0.0
    end = start + dur
    straddle = any(start + 0.3 < c < end - 0.3 for c in a.scene_changes)
    near = lambda x: any(abs(c - x) <= 0.25 for c in a.scene_changes) or x <= 0.05 or x >= a.duration - 0.05
    boring = _overlap_fraction(a.boring_ranges, start, end)
    face = 0.0
    if a.faces:
        face = sum(1 for f in a.faces if start - 0.5 <= f.get("t", -9) <= end + 0.5) / max(1, len(idx))
        face = min(1.0, face)
    return {
        "motion": motion, "sharp": sharp, "bright": bright,
        "quality": 0.55 * min(1.0, sharp) + 0.45 * exposure_ok(bright),
        "sx": sx, "sy": sy, "spread": spread, "conc": mean("conc", 0.0),
        "straddle": straddle, "boundary_start": near(start), "boundary_end": near(end),
        "boring": boring, "face": face,
    }


def _overlap_fraction(ranges: List[List[float]], start: float, end: float) -> float:
    total = max(1e-6, end - start)
    got = sum(max(0.0, min(end, b) - max(start, a)) for a, b in ranges)
    return min(1.0, got / total)


def crop_window_fraction(a: ClipAnalysis) -> float:
    """Width of a 9:16 crop window as a fraction of the source width (>=1 means no horizontal travel)."""
    if not a.width or not a.height:
        return 1.0
    return (9 / 16) * a.height / a.width


def choose_crop_x(a: ClipAnalysis, stats: dict) -> Tuple[Optional[float], float]:
    """
    Position of the crop window (0..1 across its travel range) that keeps the subject inside,
    plus a 0..1 'badness' (how much the subject spread exceeds the window).
    Returns (None, 0) when the source is not wider than the output (nothing to choose).
    """
    w = crop_window_fraction(a)
    if w >= 0.999:
        return None, 0.0
    subject_x = None
    if a.subject.get("source") == "face" and a.subject.get("x") is not None:
        subject_x = float(a.subject["x"])
    if a.visual and isinstance(a.visual.get("subject_x"), (int, float)):
        subject_x = float(a.visual["subject_x"])
    cx = subject_x if subject_x is not None else (stats["sx"] if stats["conc"] >= R.SUBJECT_CONFIDENT * 0.5 else 0.5)
    cx = R.clamp(cx, w / 2, 1 - w / 2)
    frac = (cx - w / 2) / max(1e-6, 1 - w)
    bad = R.clamp((stats["spread"] - w) / max(w, 1e-6), 0.0, 1.0)
    return round(frac, 3), bad


def find_duplicate_clips(analyses: Dict[str, ClipAnalysis]) -> Dict[str, List[str]]:
    """Clips whose sampled-frame hashes are near-identical (same footage uploaded twice)."""
    dup: Dict[str, List[str]] = {p: [] for p in analyses}
    paths = list(analyses)
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            ha = [int(x, 16) for x in analyses[paths[i]].hashes]
            hb = [int(x, 16) for x in analyses[paths[j]].hashes]
            n = min(len(ha), len(hb))
            if n >= 3 and sum(hamming(ha[k], hb[k]) for k in range(n)) / n <= 10:
                dup[paths[i]].append(paths[j])
                dup[paths[j]].append(paths[i])
    return dup


# ══════════════════════════════════════════════════════════════════════════════
# Agent
# ══════════════════════════════════════════════════════════════════════════════

class VideoAnalyzer(BaseAgent):
    agent_name = "VideoAnalyzer"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pending_cuts: Dict[str, List[float]] = {}     # cuts found during the single decode, per clip

    def _execute(self, *, clip_paths: List[str]) -> Dict[str, ClipAnalysis]:  # type: ignore[override]
        def one(p: str) -> ClipAnalysis:
            try:
                return self.analyze_clip(p) if settings.ANALYZER_ENABLED else self._light(p)
            except Exception as exc:                       # never fail the job over analysis
                self.logger.warning(f"Analysis failed for {Path(p).name}: {exc}")
                return self._light(p)

        # Clips are independent ffmpeg processes: analyse a few at a time (bounded by CPU count).
        workers = max(1, min(settings.ANALYZER_WORKERS, len(clip_paths), os.cpu_count() or 1))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            out: Dict[str, ClipAnalysis] = dict(zip(clip_paths, pool.map(one, clip_paths)))
        self._store_meta("clips_analyzed", len(out))
        return out

    # ── Public ────────────────────────────────────────────────────────────────

    def _light(self, path: str) -> ClipAnalysis:
        """ffprobe only (analysis disabled or failed): real duration/orientation, neutral scores."""
        a = ClipAnalysis(clip_path=path, degraded=True)
        self._probe(path, a)
        a.usable_ranges = [[0.0, round(a.duration, 2)]]
        a.shots = [[0.0, round(a.duration, 2)]]
        return a

    def analyze_clip(self, path: str) -> ClipAnalysis:
        key = self.content_key(path)
        cache = self._cache_file(key)
        if cache.exists():
            try:
                cached = ClipAnalysis.model_validate_json(cache.read_text(encoding="utf-8"))
                if cached.analyzer_version == ANALYZER_VERSION:
                    cached.clip_path = path
                    self.logger.info(f"Analysis cache hit: {Path(path).name}")
                    return cached
            except Exception:
                pass                                       # corrupt cache -> recompute

        a = ClipAnalysis(clip_path=path, key=key)
        self._probe(path, a)
        frames = self._sample_frames(path, a)
        if frames:
            self._metrics(frames, a)
        else:
            a.degraded = True
        self._structure(path, a)
        self._faces(path, a)
        self._subject(a)
        if settings.VISION_ENABLED and settings.ANALYZER_SAVE_KEYFRAMES:
            self._keyframes(path, a)                       # only vision uses keyframes

        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".tmp")
            tmp.write_text(a.model_dump_json(), encoding="utf-8")
            tmp.replace(cache)
        except OSError as exc:
            self.logger.warning(f"Could not write analysis cache: {exc}")
        return a

    # ── Cache ─────────────────────────────────────────────────────────────────

    @staticmethod
    def cache_dir() -> Path:
        return settings.DATA_DIR / "analysis_cache"

    def _cache_file(self, key: str) -> Path:
        return self.cache_dir() / f"{key}.json"

    @staticmethod
    def content_key(path: str) -> str:
        """Hash of size + head/middle/tail bytes + analyzer config (fast, even for big files)."""
        p = Path(path)
        size = p.stat().st_size
        h = hashlib.sha256()
        h.update(f"{size}|{ANALYZER_VERSION}|{settings.ANALYZER_MAX_SAMPLES}|{settings.ANALYZER_MAX_SECONDS}".encode())
        with open(p, "rb") as f:
            for off in (0, max(0, size // 2 - 524288), max(0, size - 1048576)):
                f.seek(off)
                h.update(f.read(1048576))
        return h.hexdigest()[:32]

    # ── ffprobe ───────────────────────────────────────────────────────────────

    def _probe(self, path: str, a: ClipAnalysis) -> None:
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path],
                capture_output=True, text=True, timeout=30,
            )
            d = json.loads(r.stdout)
            v = next(s for s in d["streams"] if s.get("codec_type") == "video")
            a.duration = float(d["format"].get("duration") or v.get("duration") or a.duration)
            w, h = int(v.get("width", 0)), int(v.get("height", 0))
            rot = 0
            try:
                rot = int(float(v.get("tags", {}).get("rotate", 0)))
            except (TypeError, ValueError):
                pass
            for sd in v.get("side_data_list", []) or []:
                if "rotation" in sd:
                    rot = int(float(sd["rotation"]))
            if abs(rot) % 180 == 90:                      # phone footage is often stored sideways
                w, h = h, w
            a.width, a.height = w, h
            a.codec = v.get("codec_name", "")
            num, _, den = str(v.get("avg_frame_rate", "0/1")).partition("/")
            a.fps = round(float(num) / float(den or 1), 2) if float(den or 1) else 0.0
            a.orientation = "landscape" if w > h * 1.05 else "portrait" if h > w * 1.05 else "square"
            a.resolution = f"{w}x{h}"
        except Exception as exc:
            a.degraded = True
            self.logger.warning(f"ffprobe failed for {Path(path).name}: {exc}")

    # ── Frame sampling ────────────────────────────────────────────────────────

    def _sample_frames(self, path: str, a: ClipAnalysis) -> List[bytes]:
        """
        Decode the clip ONCE and produce both the sampled low-res frames (stdout) and the scene-cut
        timestamps (showinfo on stderr). Falls back to separate passes if the combined graph fails.
        """
        span = max(0.5, min(a.duration, settings.ANALYZER_MAX_SECONDS))
        n_target = int(R.clamp(round(span * 2), 6, settings.ANALYZER_MAX_SAMPLES))
        fps = n_target / span
        a.timeline["fps"] = [round(fps, 4)]
        size = GRID * GRID * 3
        frames: List[bytes] = []
        try:
            if settings.ANALYZER_SCENE_DETECT:
                graph = (f"[0:v]split=2[a][b];[a]fps={fps:.4f},scale={GRID}:{GRID}:flags=area[s];"
                         f"[b]scale=160:-2,select='gt(scene,{R.CUT_SCENE_THRESHOLD})',showinfo[c]")
                r = subprocess.run(
                    ["ffmpeg", "-v", "info", "-t", f"{span:.2f}", "-i", path, "-an", "-filter_complex", graph,
                     "-map", "[s]", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1", "-map", "[c]", "-f", "null", "-"],
                    capture_output=True, timeout=240)
                if r.returncode == 0 and len(r.stdout) >= size:
                    self._pending_cuts[path] = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr.decode(errors="ignore"))]
                    data = r.stdout
                    return [data[i:i + size] for i in range(0, len(data) - size + 1, size)][: settings.ANALYZER_MAX_SAMPLES + 4]
            r = subprocess.run(
                ["ffmpeg", "-v", "error", "-t", f"{span:.2f}", "-i", path, "-an",
                 "-vf", f"fps={fps:.4f},scale={GRID}:{GRID}:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                capture_output=True, timeout=180)
            data = r.stdout
            frames = [data[i:i + size] for i in range(0, len(data) - size + 1, size)][: settings.ANALYZER_MAX_SAMPLES + 4]
        except Exception as exc:
            self.logger.warning(f"Frame sampling failed: {exc}")
        return frames

    # ── Per-frame + aggregate metrics ────────────────────────────────────────

    def _metrics(self, frames: List[bytes], a: ClipAnalysis) -> None:
        fps = a.timeline["fps"][0]
        G = GRID
        ys: List[List[int]] = []
        t, sharp, bright, sx, sy, conc, hashes = [], [], [], [], [], [], []
        contrast_acc, sat_acc = [], []
        colors: Counter = Counter()

        for i, fr in enumerate(frames):
            r, g, b = fr[0::3], fr[1::3], fr[2::3]
            y = [(299 * rr + 587 * gg + 114 * bb) // 1000 for rr, gg, bb in zip(r, g, b)]
            ys.append(y)
            n = len(y)
            s = sum(y)
            mean = s / n
            var = sum(v * v for v in y) / n - mean * mean
            bright.append(round(mean / 255, 4))
            contrast_acc.append(min(1.0, math.sqrt(max(var, 0.0)) / 70.0))
            sat_acc.append(sum((max(rr, gg, bb) - min(rr, gg, bb)) / max(1, max(rr, gg, bb))
                               for rr, gg, bb in list(zip(r, g, b))[::3]) / (n / 3))
            for rr, gg, bb in list(zip(r, g, b))[::7]:
                colors[(rr >> 6, gg >> 6, bb >> 6)] += 1

            col = [0] * G
            row = [0] * G
            grad = 0
            for yy in range(G - 1):
                a_row = y[yy * G:(yy + 1) * G]
                n_row = y[(yy + 1) * G:(yy + 2) * G]
                for xx in range(G - 1):
                    e = abs(a_row[xx] - a_row[xx + 1]) + abs(a_row[xx] - n_row[xx])
                    col[xx] += e
                    row[yy] += e
                    grad += e
            sharp.append(round(min(1.0, (grad / (2.0 * (G - 1) ** 2)) / 14.0), 4))
            sx_i, c_i = self._centroid(col)
            sy_i, _ = self._centroid(row)
            sx.append(round(sx_i, 4)); sy.append(round(sy_i, 4)); conc.append(round(c_i, 4))
            hashes.append(self._dhash(y))
            t.append(round(i / fps, 3))

        motion: List[float] = []
        shifts_x: List[float] = []
        shifts_y: List[float] = []
        for i in range(1, len(ys)):
            motion.append(sum(abs(p - q) for p, q in zip(ys[i][::2], ys[i - 1][::2])) / (len(ys[i][::2]) * 255.0))
            dx, dy = self._global_shift(ys[i - 1], ys[i])
            shifts_x.append(dx); shifts_y.append(dy)
        motion = [motion[0]] + motion if motion else [0.0] * len(ys)
        motion = [round(m, 4) for m in motion]

        a.timeline.update({"t": t, "motion": motion, "sharp": sharp, "bright": bright,
                           "sx": sx, "sy": sy, "conc": conc})
        a.hashes = [f"{h:016x}" for h in hashes]
        a.brightness_score = round(sum(bright) / len(bright), 3)
        a.contrast_score = round(sum(contrast_acc) / len(contrast_acc), 3)
        a.saturation_score = round(sum(sat_acc) / len(sat_acc), 3)
        a.sharpness_score = round(sum(sharp) / len(sharp), 3)
        a.motion_score = round(sum(motion) / len(motion), 4)
        a.is_static = a.motion_score < R.STATIC_MOTION
        mdx = sum(shifts_x) / len(shifts_x) if shifts_x else 0.0
        mdy = sum(shifts_y) / len(shifts_y) if shifts_y else 0.0
        if a.is_static:
            a.camera_motion = "static"
        elif abs(mdx) >= 1.2 and abs(mdx) >= abs(mdy):
            a.camera_motion = "pan"
        elif abs(mdy) >= 1.2:
            a.camera_motion = "tilt"
        elif a.motion_score >= 0.08:
            a.camera_motion = "moving"
        else:
            a.camera_motion = "gentle"
        a.dominant_colors = ["#%02x%02x%02x" % (r * 85, g * 85, b * 85) for (r, g, b), _ in colors.most_common(3)]
        expo = sum(exposure_ok(b) for b in bright) / len(bright)
        a.quality_score = round(0.5 * min(1.0, a.sharpness_score) + 0.3 * expo + 0.2 * a.contrast_score, 3)

    @staticmethod
    def _centroid(energy: List[int]) -> Tuple[float, float]:
        """Weighted centroid in 0..1 and how concentrated the energy is (0 = spread out, 1 = one spot)."""
        total = sum(energy)
        n = len(energy)
        if total <= 0:
            return 0.5, 0.0
        c = sum(i * e for i, e in enumerate(energy)) / total / (n - 1)
        w = n // 4
        best = max(sum(energy[i:i + w]) for i in range(0, n - w + 1, 2))
        return c, R.clamp((best / total - 0.25) / 0.75, 0.0, 1.0)

    @staticmethod
    def _dhash(y: List[int]) -> int:
        G = GRID
        bits = 0
        for r in range(8):
            base = (r * 12 + 6) * G
            vals = [sum(y[base + c * 10 + k] for k in (4, 5, 6)) for c in range(9)]
            for c in range(8):
                bits = (bits << 1) | (1 if vals[c] > vals[c + 1] else 0)
        return bits

    @staticmethod
    def _global_shift(prev: List[int], cur: List[int], max_shift: int = 6) -> Tuple[float, float]:
        """Estimate whole-frame translation from row/column luma profiles."""
        G = GRID

        def profile(y: List[int], axis: int) -> List[float]:
            if axis == 0:
                return [sum(y[yy * G + xx] for yy in range(0, G, 3)) / (G / 3) for xx in range(G)]
            return [sum(y[yy * G:(yy + 1) * G][::3]) / (G / 3) for yy in range(G)]

        def best(pa: List[float], pb: List[float]) -> float:
            errs = {}
            for s in range(-max_shift, max_shift + 1):
                lo, hi = max(0, s), min(G, G + s)
                errs[s] = sum(abs(pa[i - s] - pb[i]) for i in range(lo, hi)) / max(1, hi - lo)
            s_best = min(errs, key=errs.get)
            return float(s_best) if errs[s_best] < 0.8 * errs[0] else 0.0

        return best(profile(prev, 0), profile(cur, 0)), best(profile(prev, 1), profile(cur, 1))

    # ── Structure: cuts, ranges, segments ────────────────────────────────────

    def _structure(self, path: str, a: ClipAnalysis) -> None:
        tl = a.timeline
        ts = tl.get("t", [])
        span = (ts[-1] + 1.0 / max(tl["fps"][0], 1e-6)) if ts else a.duration
        span = min(a.duration, span) if ts else a.duration

        cuts = self._pending_cuts.pop(path, None)
        if cuts is None and settings.ANALYZER_SCENE_DETECT:
            cuts = self._ffmpeg_cuts(path, a)               # fallback: separate pass
        if cuts is None:                                   # fallback: jumps between samples
            cuts = [ts[i] for i, m in enumerate(tl.get("motion", [])) if i > 0 and m >= R.CUT_FRAME_DIFF]
        a.scene_changes = self._dedupe(sorted(c for c in cuts if 0.3 < c < a.duration - 0.3))
        bounds = [0.0] + a.scene_changes + [a.duration]
        a.shots = [[round(bounds[i], 2), round(bounds[i + 1], 2)] for i in range(len(bounds) - 1)]

        flags: List[bool] = []
        for i, t in enumerate(ts):
            is_bad = (tl["bright"][i] < R.DARK_BRIGHTNESS or tl["bright"][i] > R.BRIGHT_BRIGHTNESS
                      or tl["sharp"][i] < R.BLUR_SHARPNESS)
            flags.append(is_bad)
        step = 1.0 / max(tl.get("fps", [2.0])[0], 1e-6)
        a.boring_ranges = self._runs(ts, [m < R.BORING_MOTION for m in tl.get("motion", [])], step, R.BORING_MIN_SECONDS)
        good_runs = self._runs(ts, [not f for f in flags], step, R.MIN_SHOT)
        a.usable_ranges = [r for r in good_runs] or [[0.0, round(a.duration, 2)]]
        if a.duration > span + 0.5:                        # unsampled tail: usable but unscored
            a.usable_ranges.append([round(span, 2), round(a.duration, 2)])
        # near-duplicate moments inside one clip
        hs = [int(x, 16) for x in a.hashes]
        rep = []
        for j in range(len(hs)):
            for i in range(j):
                if ts[j] - ts[i] >= 3.0 and hamming(hs[i], hs[j]) <= R.DUP_HASH_DISTANCE:
                    rep.append([max(0.0, ts[j] - 0.5 * step), ts[j] + 0.5 * step]); break
        a.repeated_ranges = self._merge(rep)

        a.visual_energy = round(R.clamp(a.motion_score * 6 + len(a.scene_changes) / max(a.duration, 1) * 0.5, 0.0, 1.0), 3)
        # best-looking segments (non-overlapping, top 3)
        scored = []
        t0 = 0.0
        while t0 + 1.0 <= span:
            st = window_stats(a, t0, min(WINDOW, span - t0))
            score = (0.5 * st["quality"] + 0.2 * min(1.0, st["motion"] * 6) + 0.2 * st["face"]
                     + 0.1 * (0.0 if st["straddle"] else 1.0)) * (1 - 0.6 * st["boring"])
            scored.append((score, t0, min(t0 + WINDOW, span)))
            t0 += 1.0
        picked: List[dict] = []
        for score, s, e in sorted(scored, reverse=True):
            if all(e <= p["start"] or s >= p["end"] for p in picked):
                picked.append({"start": round(s, 2), "end": round(e, 2), "score": round(score, 3)})
            if len(picked) == 3:
                break
        a.best_segments = picked

    def _ffmpeg_cuts(self, path: str, a: ClipAnalysis) -> Optional[List[float]]:
        try:
            r = subprocess.run(
                ["ffmpeg", "-v", "info", "-t", f"{min(a.duration, settings.ANALYZER_MAX_SECONDS):.1f}", "-i", path,
                 "-an", "-vf", f"scale=160:-2,select='gt(scene,{R.CUT_SCENE_THRESHOLD})',showinfo",
                 "-f", "null", "-"],
                capture_output=True, text=True, timeout=180,
            )
            return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr)]
        except Exception as exc:
            self.logger.warning(f"Scene detection failed: {exc}")
            return None

    @staticmethod
    def _dedupe(vals: List[float], gap: float = 0.4) -> List[float]:
        out: List[float] = []
        for v in vals:
            if not out or v - out[-1] >= gap:
                out.append(round(v, 2))
        return out

    @staticmethod
    def _runs(ts: List[float], flags: List[bool], step: float, min_len: float) -> List[List[float]]:
        runs, start = [], None
        for i, f in enumerate(flags + [False]):
            if f and start is None:
                start = ts[i]
            if not f and start is not None:
                end = ts[i - 1] + step
                if end - start >= min_len:
                    runs.append([round(start, 2), round(end, 2)])
                start = None
        return runs

    @staticmethod
    def _merge(ranges: List[List[float]]) -> List[List[float]]:
        out: List[List[float]] = []
        for s, e in sorted(ranges):
            if out and s <= out[-1][1] + 0.01:
                out[-1][1] = max(out[-1][1], e)
            else:
                out.append([round(s, 2), round(e, 2)])
        return out

    # ── Faces (optional: OpenCV) ─────────────────────────────────────────────

    def _faces(self, path: str, a: ClipAnalysis) -> None:
        if not settings.ANALYZER_FACES or a.degraded or not a.width:
            return
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except Exception:
            return                                         # OpenCV not installed: saliency is used instead
        try:
            n = int(R.clamp(round(min(a.duration, settings.ANALYZER_MAX_SECONDS)), 3, 10))
            span = min(a.duration, settings.ANALYZER_MAX_SECONDS)
            w = 320
            h = max(2, int(w * a.height / a.width) // 2 * 2)
            r = subprocess.run(
                ["ffmpeg", "-v", "error", "-t", f"{span:.1f}", "-i", path, "-an",
                 "-vf", f"fps={n / span:.4f},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                capture_output=True, timeout=120,
            )
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            size = w * h
            for i in range(len(r.stdout) // size):
                img = np.frombuffer(r.stdout[i * size:(i + 1) * size], dtype=np.uint8).reshape(h, w)
                for (x, y, fw, fh) in cascade.detectMultiScale(img, 1.2, 5, minSize=(24, 24)):
                    a.faces.append({"t": round(i * span / n, 2), "x": round((x + fw / 2) / w, 3),
                                    "y": round((y + fh / 2) / h, 3), "w": round(fw / w, 3), "h": round(fh / h, 3)})
        except Exception as exc:
            self.logger.warning(f"Face detection skipped: {exc}")

    def _subject(self, a: ClipAnalysis) -> None:
        if a.faces:
            xs = sorted(f["x"] for f in a.faces); ys = sorted(f["y"] for f in a.faces)
            a.subject = {"x": xs[len(xs) // 2], "y": ys[len(ys) // 2], "source": "face", "confidence": 0.9}
            return
        sx, sy, conc = a.timeline.get("sx", []), a.timeline.get("sy", []), a.timeline.get("conc", [])
        if sx:
            a.subject = {"x": round(sum(sx) / len(sx), 3), "y": round(sum(sy) / len(sy), 3),
                         "source": "saliency", "confidence": round(sum(conc) / len(conc), 3)}

    # ── Keyframes ────────────────────────────────────────────────────────────

    def _keyframes(self, path: str, a: ClipAnalysis) -> None:
        if not settings.ANALYZER_SAVE_KEYFRAMES or a.degraded:
            return
        times: List[float] = []
        for seg in a.best_segments[:2]:
            times.append(seg["start"] + 0.5 * (seg["end"] - seg["start"]))
        if a.usable_ranges:
            times.append((a.usable_ranges[0][0] + a.usable_ranges[0][1]) / 2)
        times = sorted({round(R.clamp(t, 0.0, max(0.0, a.duration - 0.2)), 2) for t in times})[:3]
        out_dir = self.cache_dir() / "keyframes"
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, t in enumerate(times):
            f = out_dir / f"{a.key}_{i}.jpg"
            try:
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                                "-vf", "scale=320:-2", "-q:v", "5", str(f)], capture_output=True, timeout=30)
                if f.exists() and f.stat().st_size > 0:
                    a.keyframes.append({"t": t, "path": str(f)})
            except Exception:
                continue
