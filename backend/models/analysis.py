"""models/analysis.py: per-clip analysis produced by VideoAnalyzer (cached on disk)."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

ANALYZER_VERSION = "1"


class ClipAnalysis(BaseModel):
    clip_path: str
    key: str = ""                      # content hash used for caching
    analyzer_version: str = ANALYZER_VERSION
    degraded: bool = False             # True if probing/sampling partly failed

    # ffprobe
    duration: float = 5.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""
    orientation: str = "square"        # portrait | landscape | square (rotation-aware)
    resolution: str = ""

    # aggregate image metrics (0..1)
    brightness_score: float = 0.5
    contrast_score: float = 0.5
    saturation_score: float = 0.5
    sharpness_score: float = 0.5
    motion_score: float = 0.0          # mean frame-to-frame change
    visual_energy: float = 0.0         # motion + cut rate, normalised
    quality_score: float = 0.5
    camera_motion: str = "static"      # static | pan_left | pan_right | tilt_up | tilt_down | moving
    is_static: bool = False
    dominant_colors: List[str] = Field(default_factory=list)

    # structure
    scene_changes: List[float] = Field(default_factory=list)   # seconds
    shots: List[List[float]] = Field(default_factory=list)     # [[start, end], ...] between cuts
    usable_ranges: List[List[float]] = Field(default_factory=list)
    boring_ranges: List[List[float]] = Field(default_factory=list)
    repeated_ranges: List[List[float]] = Field(default_factory=list)
    best_segments: List[dict] = Field(default_factory=list)    # {start, end, score}

    # subject / faces
    faces: List[dict] = Field(default_factory=list)            # {t, x, y, w, h} (fractions)
    subject: Dict[str, object] = Field(default_factory=dict)   # {x, y, source: face|saliency, confidence}
    keyframes: List[dict] = Field(default_factory=list)        # {t, path}

    # sampled per-frame series (compact). Keys: t, motion, sharp, bright, sx, sy, conc
    timeline: Dict[str, List[float]] = Field(default_factory=dict)
    # 64-bit perceptual hashes of the sampled frames as hex strings (floats would lose precision)
    hashes: List[str] = Field(default_factory=list)

    # optional vision-model output (None if VISION_ENABLED is false)
    visual: Optional[Dict[str, object]] = None
    # On-screen text detection needs OCR, which is not bundled: always None.
    on_screen_text: Optional[List[str]] = None
