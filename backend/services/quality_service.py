"""
services/quality_service.py
---------------------------
Deterministic technical validation of the rendered Reel. Produces a small report that is
returned with the job result. Critical problems (missing/corrupt file, wrong resolution,
no video stream) fail the job; everything else is a warning.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

from core.config import settings
from core.exceptions import VideoCompositionError
from core.logging import get_logger

logger = get_logger("QualityService")


class QualityService:
    def check(
        self,
        output_path: str,
        *,
        expected_duration: float,
        plan_duration: Optional[float] = None,
        subtitle_count: int = 0,
        captions_expected: bool = True,
    ) -> dict:
        errors, warnings = [], []
        report: dict = {"ok": True, "errors": errors, "warnings": warnings}
        p = Path(output_path)
        if not p.exists() or p.stat().st_size == 0:
            raise VideoCompositionError("Validation failed: the output file is missing or empty.")
        report["file_size_mb"] = round(p.stat().st_size / 1_048_576, 2)

        info = self._probe(output_path)
        v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
        au = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
        if v is None:
            raise VideoCompositionError("Validation failed: the output has no video stream.")
        w, h = int(v.get("width", 0)), int(v.get("height", 0))
        num, _, den = str(v.get("avg_frame_rate", "0/1")).partition("/")
        fps = round(float(num) / float(den or 1), 2) if float(den or 1) else 0.0
        actual = float(info.get("format", {}).get("duration") or 0.0)
        report["video"] = {"width": w, "height": h, "fps": fps, "codec": v.get("codec_name"),
                           "pix_fmt": v.get("pix_fmt"), "duration": round(actual, 2)}
        report["audio"] = bool(au)

        if (w, h) != (settings.VIDEO_WIDTH, settings.VIDEO_HEIGHT):
            errors.append(f"Resolution is {w}x{h}, expected {settings.VIDEO_WIDTH}x{settings.VIDEO_HEIGHT}.")
        if abs(fps - settings.VIDEO_FPS) > 1.0:
            warnings.append(f"Frame rate is {fps}, expected {settings.VIDEO_FPS}.")
        if v.get("codec_name") != "h264":
            warnings.append(f"Video codec is {v.get('codec_name')}, expected h264.")
        if au is None:
            errors.append("The video has no audio track.")
        if actual < 1.0:
            errors.append("The video is shorter than one second.")
        if expected_duration and abs(actual - expected_duration) > max(0.8, 0.05 * expected_duration):
            warnings.append(f"Length is {actual:.1f}s but the voiceover is {expected_duration:.1f}s.")
        if plan_duration and abs(actual - plan_duration) > max(1.2, 0.08 * plan_duration):
            warnings.append(f"Length differs from the editing plan ({plan_duration:.1f}s planned).")
        if captions_expected and subtitle_count == 0:
            warnings.append("Captions were expected but none were generated.")
        report["captions"] = {"expected": captions_expected, "entries": subtitle_count}

        mode = settings.QUALITY_DECODE
        if mode != "off":
            # Truncation and container damage show up at the ends of the file, so decoding the first and last
            # seconds is enough for a file we just wrote ourselves. "full" decodes everything.
            probes = [["-i", output_path]] if mode == "full" else [["-t", "3", "-i", output_path], ["-sseof", "-3", "-i", output_path]]
            bad = [r.stderr.strip() for r in (subprocess.run(["ffmpeg", "-v", "error", *args, "-f", "null", "-"], capture_output=True,
                                                             text=True, timeout=300) for args in probes) if r.stderr.strip()]
            report["decode_ok"] = not bad
            if bad:
                errors.append("The video file has decoding errors.")
        report["ok"] = not errors
        if errors:
            logger.error(f"Output validation failed: {errors}")
            raise VideoCompositionError("Validation failed: " + " ".join(errors))
        if warnings:
            logger.warning(f"Output validation warnings: {warnings}")
        return report

    @staticmethod
    def _probe(path: str) -> dict:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path],
                           capture_output=True, text=True, timeout=30)
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError:
            return {}
