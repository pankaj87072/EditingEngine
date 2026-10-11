"""
agents/vision_agent.py
----------------------
OPTIONAL. Describes clips with a vision-capable model using at most VISION_MAX_FRAMES small
keyframes per clip (320px JPEGs) plus metadata. Never sends a video.

Cached per clip content hash + analyzer version + model, so a clip is described once.
Disabled unless VISION_ENABLED=true and ANTHROPIC_API_KEY is set. Any failure leaves the
deterministic analysis untouched.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Dict, Optional

from agents.base_agent import BaseAgent
from agents.video_analyzer import VideoAnalyzer
from core import llm
from core.config import settings
from models.analysis import ANALYZER_VERSION, ClipAnalysis

TAGS = {
    "person", "speaking", "face", "group", "product", "closeup", "wide", "hands", "action", "food", "screen",
    "office", "outdoor", "indoor", "text", "logo", "animal", "vehicle", "nature", "city", "kitchen", "laptop",
    "phone", "camera", "smile", "reaction", "detail", "crowd",
}
SHOT_TYPES = {"close_up", "medium", "wide", "screen", "detail"}
CAPTION_SAFE = {"top", "bottom", "none"}

SYSTEM = """You describe video clips for an automated editor. You get a few keyframes and metadata.
Reply with ONLY compact JSON:
{"tags":[...],"shot_type":"close_up|medium|wide|screen|detail","description":"max 20 words",
 "subject_x":0.0-1.0 or null,"hook_time":seconds or null,"caption_safe":"top|bottom|none","movement":"left|right|up|down|toward|away|none"}
tags must come from: """ + ", ".join(sorted(TAGS)) + """.
subject_x is the horizontal position of the main subject (0 left, 1 right). caption_safe is where
captions will NOT cover the subject. hook_time is the most attention-grabbing moment."""


class VisionAgent(BaseAgent):
    agent_name = "VisionAgent"

    @staticmethod
    def enabled() -> bool:
        return settings.VISION_ENABLED and llm.available()

    def _execute(self, *, analyses: Dict[str, ClipAnalysis]) -> Dict[str, ClipAnalysis]:  # type: ignore[override]
        if not self.enabled():
            return analyses
        for p, a in analyses.items():
            try:
                a.visual = self._describe(a)
            except Exception as exc:
                self.logger.warning(f"Vision skipped for {Path(p).name}: {exc}")
        return analyses

    def _cache_file(self, a: ClipAnalysis) -> Path:
        k = hashlib.sha256(f"{a.key}|{ANALYZER_VERSION}|{settings.VISION_MODEL}".encode()).hexdigest()[:24]
        return VideoAnalyzer.cache_dir() / f"vision_{k}.json"

    def _describe(self, a: ClipAnalysis) -> Optional[dict]:
        cache = self._cache_file(a)
        if cache.exists():
            return json.loads(cache.read_text(encoding="utf-8"))
        if not any(Path(k.get("path", "")).exists() for k in a.keyframes) and Path(a.clip_path).exists():
            a.keyframes = []
            VideoAnalyzer()._keyframes(a.clip_path, a)      # generated lazily: only vision needs them
        frames = [k for k in a.keyframes if Path(k.get("path", "")).exists()][: settings.VISION_MAX_FRAMES]
        if not frames:
            return None
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                    "data": base64.b64encode(Path(k["path"]).read_bytes()).decode()}} for k in frames]
        content.append({"type": "text", "text": json.dumps({
            "file": Path(a.clip_path).name, "duration": round(a.duration, 1), "orientation": a.orientation,
            "keyframe_times": [k["t"] for k in frames], "motion": a.motion_score, "camera": a.camera_motion,
        })})
        raw = llm.call_messages(system=SYSTEM, content=content, model=settings.VISION_MODEL,
                                max_tokens=400, timeout=settings.PLANNER_TIMEOUT)
        clean = self.validate(llm.extract_json(raw), a.duration)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(clean), encoding="utf-8")
        return clean

    @staticmethod
    def validate(d: dict, duration: float) -> dict:
        """Never trust model output: keep only known tags/enums and clamp numbers."""
        tags = [str(t).lower() for t in d.get("tags", []) if isinstance(t, str) and str(t).lower() in TAGS][:8]
        st = str(d.get("shot_type", "")).lower()
        sx, ht = d.get("subject_x"), d.get("hook_time")
        cs = str(d.get("caption_safe", "none")).lower()
        return {
            "tags": tags,
            "shot_type": st if st in SHOT_TYPES else "medium",
            "description": str(d.get("description", ""))[:160],
            "subject_x": max(0.0, min(1.0, float(sx))) if isinstance(sx, (int, float)) and not isinstance(sx, bool) else None,
            "hook_time": max(0.0, min(duration, float(ht))) if isinstance(ht, (int, float)) and not isinstance(ht, bool) else None,
            "caption_safe": cs if cs in CAPTION_SAFE else "none",
        }
