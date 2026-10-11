"""
agents/video_composition_agent.py
-----------------------------------
VideoCompositionAgent
---------------------
Responsibility:
  - Prepare each clip (scale to vertical 9:16).
  - Apply Ken Burns zoom effect.
  - Apply fade / crossfade transitions.
  - Concatenate all clips.
  - Mux with voiceover audio.
  - Burn subtitles.
  - Export final Instagram-ready MP4.

This is the most complex agent — it orchestrates multiple FFmpeg
operations in a defined pipeline, using helpers from ffmpeg_utils.

Input kwargs:
    scene_mappings (List[SceneMappingResult]): From SceneMappingAgent.
    audio_result   (AudioResult):              From AudioGenerationAgent.
    subtitles      (List[SubtitleEntry]):       From SubtitleTimingAgent.
    output_dir     (str):                       Where to save everything.
    job_id         (str):                       Used for file naming.
    transition     (TransitionType):            Fade, crossfade, or zoom.

Returns:
    str  — Absolute path to the final MP4.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from agents.base_agent import BaseAgent
from agents.subtitle_timing_agent import SubtitleTimingAgent
from core.config import settings
from core.exceptions import JobCancelledError, VideoCompositionError
from models.schema import (
    AudioResult,
    SceneMappingResult,
    SubtitleEntry,
    TransitionType,
)
from utils import ffmpeg_utils


class VideoCompositionAgent(BaseAgent):
    agent_name = "VideoCompositionAgent"

    def _execute(  # type: ignore[override]
        self,
        *,
        scene_mappings: List[SceneMappingResult],
        audio_result: AudioResult,
        subtitles: List[SubtitleEntry],
        output_dir: str,
        job_id: str,
        transition: TransitionType = TransitionType.FADE,
        zoom: float | None = None,
        subtitle_position: str = "bottom",
        caption_style: str = "classic",
        should_cancel=None,
        caption_punch: bool = False,
        caption_zones=None,
    ) -> str:

        if not scene_mappings:
            raise VideoCompositionError("No scene mappings provided.")

        work_dir = Path(output_dir) / "work"
        work_dir.mkdir(parents=True, exist_ok=True)

        plan_mode = any(m.join_after != "legacy" for m in scene_mappings)
        if plan_mode and settings.SINGLE_PASS_COMPOSITION:
            # ── FAST PATH: one filter graph, one encode. If anything goes wrong, fall through to the
            #    proven multi-stage path below, so a graph/codec problem never fails the job. ──
            try:
                return self._compose_single_pass(
                    scene_mappings, audio_result, subtitles, output_dir, job_id, work_dir,
                    subtitle_position, caption_style, caption_punch, caption_zones, should_cancel)
            except JobCancelledError:
                raise
            except Exception as exc:
                self.logger.warning(f"Single-pass composition failed ({exc}); using the multi-stage path.")

        concat_path = str(work_dir / f"{job_id}_concat.mp4")
        if plan_mode:
            # ── Plan execution (editing engine): one FFmpeg pass per shot, join-aware concat ──
            self._log_step(f"Stage 1/4 — Rendering {len(scene_mappings)} planned shots")
            shots = self._render_shots(scene_mappings, work_dir, should_cancel)
            self._log_step("Stage 2/4 — Joining shots (cuts + blends)")
            concatenated = ffmpeg_utils.concat_with_joins(
                shots, [(m.join_after, m.join_dur) for m in scene_mappings[:-1]], concat_path
            )
        else:
            # ── Legacy path (plans created before the editing engine) ──────────
            self._log_step("Stage 1/5 — Scaling clips to vertical 9:16")
            scaled_clips = self._scale_clips(scene_mappings, work_dir, should_cancel)
            self._log_step("Stage 2/5 — Applying Ken Burns zoom effect")
            zoomed_clips = self._apply_zoom(scaled_clips, scene_mappings, work_dir, zoom, should_cancel)
            if should_cancel:
                should_cancel()
            self._log_step(f"Stage 3/5 — Applying '{transition}' transition")
            concatenated = self._concat_with_transition(zoomed_clips, concat_path, transition)
        if should_cancel:
            should_cancel()

        # ── Stage 4: Mux audio ────────────────────────────────────────────────
        self._log_step("Stage 4/5 — Muxing audio")
        muxed_path = str(work_dir / f"{job_id}_muxed.mp4")
        muxed = ffmpeg_utils.mux_audio_video(
            video_path=concatenated,
            audio_path=audio_result.audio_path,
            output_path=muxed_path,
            target_duration=audio_result.duration,
        )

        # ── Stage 5: Burn subtitles → final export ────────────────────────────
        self._log_step("Stage 5/5 — Burning subtitles and exporting")
        final_path = str(Path(output_dir) / f"{job_id}_final.mp4")
        final = self._burn_and_export(
            muxed, subtitles, final_path, work_dir, job_id,
            subtitle_position, caption_style,
            emphasis=[w for m in scene_mappings for w in m.caption_emphasis],
            punch=caption_punch, zones=caption_zones,
        )

        self._store_meta("final_path", final)
        return final

    # ── Stage implementations ─────────────────────────────────────────────────

    def _compose_single_pass(
        self, scene_mappings, audio_result, subtitles, output_dir, job_id, work_dir,
        subtitle_position, caption_style, caption_punch, caption_zones, should_cancel,
    ) -> str:
        """Plan -> ONE ffmpeg run (trim/speed/crop/motion/joins/captions/audio) -> final MP4."""
        self._log_step(f"Single-pass composition: {len(scene_mappings)} shots, one encode")
        srt_path = str(work_dir / f"{job_id}.srt")
        Path(srt_path).write_text(SubtitleTimingAgent.to_srt(subtitles), encoding="utf-8")
        sub_filter = ffmpeg_utils.prepare_subtitles(
            srt_path, subtitle_position, caption_style,
            emphasis=[w for m in scene_mappings for w in m.caption_emphasis], punch=caption_punch, zones=caption_zones)
        if should_cancel:
            should_cancel()
        music = settings.BACKGROUND_MUSIC_PATH if settings.BACKGROUND_MUSIC_PATH and Path(settings.BACKGROUND_MUSIC_PATH).exists() else None
        shots = [{
            "clip": m.clip_path, "start": m.start, "duration": m.duration or m.clip_duration, "speed": m.speed,
            "crop": m.crop, "crop_x": m.crop_x, "motion": m.motion, "zoom": m.zoom or 1.0, "punch_at": m.punch_at,
            "source_duration": m.clip_duration, "flip": bool(i % 2), "join": m.join_after, "join_dur": m.join_dur,
        } for i, m in enumerate(scene_mappings)]
        final_path = str(Path(output_dir) / f"{job_id}_final.mp4")
        ffmpeg_utils.compose_single_pass(
            shots=shots, audio_path=audio_result.audio_path, subtitle_filter=sub_filter,
            output_path=final_path, music_path=music)
        return final_path

    def _render_shots(self, scene_mappings, work_dir: Path, should_cancel=None) -> List[str]:
        """Execute the plan: trim, speed, smart-crop and motion for every shot."""
        out: List[str] = []
        for i, m in enumerate(scene_mappings):
            if should_cancel:
                should_cancel()
            path = str(work_dir / f"shot_{i:03d}.mp4")
            ffmpeg_utils.render_shot(
                m.clip_path, path,
                start=m.start, duration=m.duration or m.clip_duration, speed=m.speed,
                crop=m.crop, crop_x=m.crop_x, motion=m.motion, zoom=m.zoom or 1.0,
                punch_at=m.punch_at, source_duration=m.clip_duration, flip=bool(i % 2),
            )
            out.append(path)
            self._log_step(f"  Shot {i}: {Path(m.clip_path).name} @ {m.start:.1f}s, {m.motion}, speed {m.speed}")
        return out

    def _scale_clips(
        self,
        scene_mappings: List[SceneMappingResult],
        work_dir: Path,
        should_cancel=None,
    ) -> List[str]:
        """Scale each source clip to vertical resolution (trimmed per the plan)."""
        scaled: List[str] = []
        for i, mapping in enumerate(scene_mappings):
            if should_cancel:
                should_cancel()
            out = str(work_dir / f"scaled_{i:03d}.mp4")
            ffmpeg_utils.scale_clip_to_vertical(
                mapping.clip_path,
                out,
                start=mapping.start,
                duration=mapping.duration,
                crop=mapping.crop,
                source_duration=mapping.clip_duration,
            )
            scaled.append(out)
            self._log_step(f"  Scaled clip {i}: {Path(mapping.clip_path).name}")
        return scaled

    def _apply_zoom(
        self,
        scaled_clips: List[str],
        scene_mappings: List[SceneMappingResult],
        work_dir: Path,
        zoom: float | None = None,
        should_cancel=None,
    ) -> List[str]:
        """Apply Ken Burns zoom effect to each scaled clip."""
        zoomed: List[str] = []
        for i, (clip, mapping) in enumerate(zip(scaled_clips, scene_mappings)):
            if should_cancel:
                should_cancel()
            out = str(work_dir / f"zoomed_{i:03d}.mp4")
            duration = mapping.duration or mapping.clip_duration
            ffmpeg_utils.apply_ken_burns(clip, out, duration, mapping.zoom or zoom)
            zoomed.append(out)
            self._log_step(f"  Zoomed clip {i}: {duration:.1f}s")
        return zoomed

    def _concat_with_transition(
        self,
        clips: List[str],
        output_path: str,
        transition: TransitionType,
    ) -> str:
        """Concatenate clips with the chosen transition type."""

        if transition == TransitionType.CROSSFADE:
            return ffmpeg_utils.create_crossfade_concat(clips, output_path)

        elif transition == TransitionType.FADE:
            # Apply fade in/out on each clip, then simple concat
            faded = self._apply_fades(clips)
            return self._simple_concat(faded, output_path)

        elif transition == TransitionType.ZOOM:
            # Ken Burns already applied — just crossfade
            return ffmpeg_utils.create_crossfade_concat(clips, output_path)

        else:
            # No transition — raw concat
            return self._simple_concat(clips, output_path)

    def _apply_fades(self, clips: List[str]) -> List[str]:
        """Apply per-clip fade-in / fade-out. Returns new paths."""
        faded: List[str] = []
        for i, clip in enumerate(clips):
            parent = Path(clip).parent
            out = str(parent / f"faded_{i:03d}.mp4")
            ffmpeg_utils.add_fade_transition(
                input_path=clip,
                output_path=out,
                duration=0.4,
            )
            faded.append(out)
        return faded

    def _simple_concat(self, clips: List[str], output_path: str) -> str:
        """
        Concatenate clips using FFmpeg concat demuxer (file list).
        This is the fastest concatenation method for same-codec clips.
        """
        import tempfile

        # Write concat file list
        list_file = str(Path(output_path).parent / "concat_list.txt")
        with open(list_file, "w") as f:
            for clip in clips:
                # Paths in concat list must be escaped
                safe_path = clip.replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")

        import subprocess
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-an",
            output_path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            raise VideoCompositionError(
                f"Concat failed: {result.stderr[-400:]}"
            )
        return output_path

    def _burn_and_export(
        self,
        muxed_path: str,
        subtitles: List[SubtitleEntry],
        final_path: str,
        work_dir: Path,
        job_id: str,
        subtitle_position: str = "bottom",
        caption_style: str = "classic",
        emphasis: list | None = None,
        punch: bool = False,
        zones: list | None = None,
    ) -> str:
        """Write SRT file, burn subtitles, then export final."""

        # Write SRT to disk
        srt_content = SubtitleTimingAgent.to_srt(subtitles)
        srt_path = str(work_dir / f"{job_id}.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        # Burn subtitles into video
        subtitled_path = str(work_dir / f"{job_id}_subtitled.mp4")
        try:
            ffmpeg_utils.burn_subtitles(
                muxed_path, srt_path, subtitled_path,
                position=subtitle_position, caption_style=caption_style,
                emphasis=emphasis, punch=punch, zones=zones,
            )
        except Exception as e:
            self.logger.warning(
                f"Subtitle burning failed ({e}). "
                "Exporting without subtitles."
            )
            subtitled_path = muxed_path   # Fall back to muxed video

        # Final export (re-encode for Instagram compatibility)
        ffmpeg_utils.export_final(subtitled_path, final_path)
        return final_path
