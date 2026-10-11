"""
core/editing_rules.py
---------------------
ONE place for every tunable number used by the deterministic editing engine.
Nothing in agents/ should hardcode these. Tune here.

"Trending" in this project means configurable, measurable editing patterns
(shot length, cut rhythm, motion, caption behaviour). It does not copy any
specific creator and makes no promise about performance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ── Global limits (everything the planner/AI is clamped to) ───────────────────
ZOOM_MIN, ZOOM_MAX = 1.0, 1.25
SPEED_MIN, SPEED_MAX = 0.85, 1.20          # conservative: no unnatural motion
MIN_SHOT = 0.6                             # seconds; never plan shorter than this
MAX_SHOTS_PER_SCENE = 6
SEGMENT_STEP = 0.5                         # candidate window step (s)
LOOP_PENALTY_DURATION_FIT = 0.35           # duration_fit score when a clip must loop

# ── Analysis thresholds (normalised 0..1 metrics from VideoAnalyzer) ──────────
STATIC_MOTION = 0.012                      # below = static shot
BORING_MOTION = 0.02                       # static AND long -> boring
BORING_MIN_SECONDS = 2.5
LOW_QUALITY = 0.35                         # below = avoid unless nothing else
DARK_BRIGHTNESS, BRIGHT_BRIGHTNESS = 0.12, 0.92
BLUR_SHARPNESS = 0.05                      # below = blurry
CUT_SCENE_THRESHOLD = 0.30                 # ffmpeg select(scene) threshold
CUT_FRAME_DIFF = 0.22                      # sampled-frame cut fallback
DUP_HASH_DISTANCE = 6                      # hamming distance for near-duplicates
SUBJECT_CONFIDENT = 0.35                   # saliency concentration needed to trust subject_y

# ── Score weights (clip_score = Σ positive − Σ penalties) ─────────────────────
SCORE_WEIGHTS: Dict[str, float] = {
    "semantic_match": 0.22,
    "visual_relevance": 0.10,
    "motion_match": 0.12,
    "quality": 0.16,
    "duration_fit": 0.08,
    "variety": 0.08,
    "hook_bonus": 0.12,
    "continuity_bonus": 0.04,
    "boundary_bonus": 0.04,
    # penalties (subtracted)
    "repetition_penalty": 0.45,
    "boring_penalty": 0.20,
    "bad_crop_penalty": 0.20,
    "straddle_penalty": 0.10,
}

# ── Intensity (user's Calm / Balanced / Dynamic) ──────────────────────────────
INTENSITY: Dict[str, Dict[str, float]] = {
    "calm":     {"motion": 0.6, "shot_scale": 1.20},
    "balanced": {"motion": 1.0, "shot_scale": 1.00},
    "dynamic":  {"motion": 1.4, "shot_scale": 0.85},
}

# ── Motion presets ────────────────────────────────────────────────────────────
MOTION_PRESETS = (
    "static", "push_in", "pull_out", "pan_h", "pan_v",
    "dynamic_push", "punch", "cinematic_drift",
)
JOIN_TYPES = ("cut", "dissolve", "smoothleft", "zoomin", "fadeblack")  # ffmpeg xfade names
EFFECT_PRESETS = ("none", "punch")
XFADE_NAME = {"dissolve": "fade", "smoothleft": "smoothleft", "zoomin": "zoomin", "fadeblack": "fadeblack"}
BASE_ZOOM = 0.08            # peak zoom-in above 1.0 at motion strength 1.0

# ── Caption rules ─────────────────────────────────────────────────────────────
CAPTION_MIN_WORDS = 2
CAPTION_PAUSE_CHARS = ".!?;:,"           # phrase boundaries
CAPTION_AVOID_SUBJECT = True             # move a card away from faces/products
CAPTION_SUBJECT_LOW, CAPTION_SUBJECT_HIGH = 0.62, 0.38

# ── Roles ─────────────────────────────────────────────────────────────────────
ROLES = ("hook", "intro", "body", "payoff", "cta")


@dataclass(frozen=True)
class StyleRules:
    key: str
    label: str
    description: str
    shot_min: float
    shot_max: float
    hook_shot_max: float
    cta_shot_max: float
    scene_join: str                 # join between scenes
    scene_join_dur: float
    inshot_join: str                # join between shots inside one scene
    inshot_join_dur: float
    accent_join: Optional[str]      # motion transition on role changes (sparingly)
    accent_every: int               # at most one accent per N joins (0 = never)
    motion_strength: float          # multiplies BASE_ZOOM
    motion_pool: Dict[str, List[str]] = field(default_factory=dict)  # role -> presets
    punch_on_emphasis: bool = False
    speed_boring: float = 1.0       # applied to boring footage
    speed_important: float = 1.0    # applied to important high-motion moments
    caption_max_words: int = 4
    caption_punch: bool = False
    weight_mult: Dict[str, float] = field(default_factory=dict)
    legacy_transition: str = "fade"  # value written to Job.transition for compatibility


STYLES: Dict[str, StyleRules] = {
    "clean": StyleRules(
        key="clean", label="Clean",
        description="Simple cuts, subtle movement, readable captions.",
        shot_min=2.2, shot_max=4.5, hook_shot_max=2.8, cta_shot_max=4.0,
        scene_join="cut", scene_join_dur=0.0, inshot_join="cut", inshot_join_dur=0.0,
        accent_join=None, accent_every=0, motion_strength=0.7,
        motion_pool={"hook": ["push_in"], "intro": ["push_in", "static"], "body": ["push_in", "static", "pull_out"],
                     "payoff": ["push_in"], "cta": ["static"]},
        speed_boring=1.08, caption_max_words=4, legacy_transition="none",
    ),
    "social_punchy": StyleRules(
        key="social_punchy", label="Social Punchy",
        description="Faster cuts, emphasis moments, stronger motion.",
        shot_min=1.1, shot_max=2.6, hook_shot_max=1.8, cta_shot_max=2.6,
        scene_join="cut", scene_join_dur=0.0, inshot_join="cut", inshot_join_dur=0.0,
        accent_join="smoothleft", accent_every=4, motion_strength=1.3,
        motion_pool={"hook": ["dynamic_push", "punch"], "intro": ["dynamic_push", "push_in"],
                     "body": ["push_in", "punch", "pan_h", "dynamic_push"], "payoff": ["punch", "dynamic_push"],
                     "cta": ["push_in"]},
        punch_on_emphasis=True, speed_boring=1.15, speed_important=0.92, caption_max_words=3, caption_punch=True,
        weight_mult={"variety": 1.4, "motion_match": 1.3, "hook_bonus": 1.3}, legacy_transition="none",
    ),
    "cinematic": StyleRules(
        key="cinematic", label="Cinematic",
        description="Longer shots, smooth movement, subtle transitions.",
        shot_min=3.2, shot_max=6.5, hook_shot_max=4.0, cta_shot_max=5.0,
        scene_join="dissolve", scene_join_dur=0.5, inshot_join="cut", inshot_join_dur=0.0,
        accent_join=None, accent_every=0, motion_strength=0.8,
        motion_pool={"hook": ["cinematic_drift", "push_in"], "intro": ["cinematic_drift", "pan_h"],
                     "body": ["cinematic_drift", "pan_h", "pull_out", "pan_v"], "payoff": ["push_in", "cinematic_drift"],
                     "cta": ["static", "cinematic_drift"]},
        speed_boring=1.0, speed_important=0.9, caption_max_words=5,
        weight_mult={"quality": 1.4, "continuity_bonus": 2.0, "variety": 0.7}, legacy_transition="crossfade",
    ),
    "dynamic": StyleRules(
        key="dynamic", label="Dynamic",
        description="More visual changes, stronger motion and energetic pacing.",
        shot_min=1.3, shot_max=3.0, hook_shot_max=2.0, cta_shot_max=3.0,
        scene_join="cut", scene_join_dur=0.0, inshot_join="cut", inshot_join_dur=0.0,
        accent_join="zoomin", accent_every=5, motion_strength=1.2,
        motion_pool={"hook": ["dynamic_push", "punch"], "intro": ["dynamic_push", "pan_h"],
                     "body": ["dynamic_push", "pan_h", "pan_v", "push_in", "pull_out"],
                     "payoff": ["dynamic_push", "punch"], "cta": ["push_in"]},
        punch_on_emphasis=True, speed_boring=1.12, speed_important=0.95, caption_max_words=3, caption_punch=True,
        weight_mult={"variety": 1.3, "motion_match": 1.4}, legacy_transition="zoom",
    ),
    "storytelling": StyleRules(
        key="storytelling", label="Storytelling",
        description="Longer visual continuity and scene-aware cuts.",
        shot_min=2.8, shot_max=5.5, hook_shot_max=3.2, cta_shot_max=4.5,
        scene_join="dissolve", scene_join_dur=0.4, inshot_join="cut", inshot_join_dur=0.0,
        accent_join=None, accent_every=0, motion_strength=0.75,
        motion_pool={"hook": ["push_in"], "intro": ["push_in", "cinematic_drift"],
                     "body": ["cinematic_drift", "push_in", "pan_h", "static"], "payoff": ["push_in"], "cta": ["static"]},
        speed_boring=1.05, caption_max_words=4,
        weight_mult={"continuity_bonus": 3.0, "semantic_match": 1.2, "variety": 0.8}, legacy_transition="crossfade",
    ),
    "product_focus": StyleRules(
        key="product_focus", label="Product Focus",
        description="Keeps products and subjects prominent with clear captions.",
        shot_min=2.0, shot_max=4.0, hook_shot_max=2.4, cta_shot_max=4.0,
        scene_join="dissolve", scene_join_dur=0.25, inshot_join="cut", inshot_join_dur=0.0,
        accent_join=None, accent_every=0, motion_strength=0.6,
        motion_pool={"hook": ["push_in"], "intro": ["push_in", "static"], "body": ["push_in", "static", "pan_h"],
                     "payoff": ["push_in"], "cta": ["static"]},
        speed_boring=1.0, caption_max_words=4,
        weight_mult={"visual_relevance": 1.6, "bad_crop_penalty": 1.8, "semantic_match": 1.3}, legacy_transition="fade",
    ),
}
DEFAULT_STYLE = "clean"


def get_style(key: Optional[str]) -> StyleRules:
    return STYLES.get((key or DEFAULT_STYLE).lower(), STYLES[DEFAULT_STYLE])


def weight(style: StyleRules, name: str) -> float:
    return SCORE_WEIGHTS[name] * style.weight_mult.get(name, 1.0)


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))
