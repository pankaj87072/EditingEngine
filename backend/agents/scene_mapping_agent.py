"""
agents/scene_mapping_agent.py
------------------------------
SceneMappingAgent
-----------------
Responsibility:
  - Receive a list of scenes and a list of uploaded clip paths.
  - Map each scene to the most suitable clip.
  - If there are more scenes than clips, recycle clips intelligently
    (avoid back-to-back repeats).
  - Probe actual clip duration using FFprobe.

Input kwargs:
    scenes     (List[ScriptScene]): Output from ScriptSegmentationAgent.
    clip_paths (List[str]):         Absolute paths to uploaded video clips.

Returns:
    List[SceneMappingResult]
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import List, Optional

from agents.base_agent import BaseAgent
from core.exceptions import SceneMappingError
from models.schema import SceneMappingResult, ScriptScene


class SceneMappingAgent(BaseAgent):
    agent_name = "SceneMappingAgent"

    def _execute(  # type: ignore[override]
        self,
        *,
        scenes: List[ScriptScene],
        clip_paths: List[str],
    ) -> List[SceneMappingResult]:

        if not clip_paths:
            raise SceneMappingError("No video clips provided.")
        if not scenes:
            raise SceneMappingError("No scenes provided.")

        # Validate all clips exist
        valid_clips = self._validate_clips(clip_paths)
        if not valid_clips:
            raise SceneMappingError("None of the provided clip paths exist.")

        self._log_step(f"Valid clips: {len(valid_clips)}, Scenes: {len(scenes)}")

        # Get actual durations for each clip
        clip_durations = {
            clip: self._probe_duration(clip) for clip in valid_clips
        }

        mappings: List[SceneMappingResult] = []
        last_used_index: Optional[int] = None

        for scene in scenes:
            clip_index = self._select_clip(
                scene_index=scene.scene_index,
                total_clips=len(valid_clips),
                last_used_index=last_used_index,
            )
            chosen_clip = valid_clips[clip_index]
            last_used_index = clip_index

            mapping = SceneMappingResult(
                scene_index=scene.scene_index,
                clip_path=chosen_clip,
                clip_duration=clip_durations.get(chosen_clip, 5.0),
                scene_text=scene.text,
            )
            mappings.append(mapping)
            self._log_step(
                f"Scene {scene.scene_index} → clip [{clip_index}] "
                f"({Path(chosen_clip).name}, "
                f"{clip_durations.get(chosen_clip, 0):.1f}s)"
            )

        self._store_meta("total_mappings", len(mappings))
        return mappings

    # ── Private helpers ───────────────────────────────────────────────────────

    def _validate_clips(self, paths: List[str]) -> List[str]:
        """Return only clips that exist on disk."""
        return [p for p in paths if Path(p).exists()]

    def _select_clip(
        self,
        scene_index: int,
        total_clips: int,
        last_used_index: Optional[int],
    ) -> int:
        """
        Round-robin selection with a 'no-repeat' rule:
        avoids using the same clip twice in a row.
        """
        candidate = scene_index % total_clips

        # If candidate is same as last and we have alternatives, shift by 1
        if candidate == last_used_index and total_clips > 1:
            candidate = (candidate + 1) % total_clips

        return candidate

    def _probe_duration(self, clip_path: str) -> float:
        """
        Use ffprobe to get the actual duration of a video clip.
        Falls back to 5.0s if ffprobe is unavailable or fails.
        """
        try:
            cmd = [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                clip_path,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                duration = float(data["format"].get("duration", 5.0))
                return round(duration, 3)
        except Exception as exc:
            self.logger.warning(
                f"ffprobe failed for {clip_path}: {exc}. Using 5.0s default."
            )
        return 5.0
