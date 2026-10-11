"""
services/video_service.py
--------------------------
VideoService
------------
The Planner + Executor orchestrator.

This service wires all five agents together in the correct order,
passing each agent's output as the next agent's input.
It also updates the job's progress at each stage.

Pipeline:
  ScriptSegmentationAgent
        ↓  scenes
  SceneMappingAgent
        ↓  scene_mappings
  AudioGenerationAgent
        ↓  audio_result
  SubtitleTimingAgent
        ↓  subtitles
  VideoCompositionAgent
        ↓  final_mp4_path

The service is called by the Celery worker task.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import List

import json

from agents.audio_generation_agent import AudioGenerationAgent
from agents.editing_engine import EditingEngine, caption_zones, plan_to_json, retime_plan
from agents.editing_plan_agent import EditingPlanAgent, validate_plan
from agents.video_analyzer import VideoAnalyzer
from agents.vision_agent import VisionAgent
from agents.scene_mapping_agent import SceneMappingAgent
from agents.script_segmentation_agent import ScriptSegmentationAgent
from agents.subtitle_timing_agent import SubtitleTimingAgent
from agents.video_composition_agent import VideoCompositionAgent
from core import editing_rules as R
from core.exceptions import JobCancelledError, VideoCompositionError, VideoGenBaseError
from core.config import settings
from core.logging import get_logger
from models.schema import Job, JobStatus, TransitionType, TTSProvider  # noqa: F401
from services.job_service import JobService
from services.quality_service import QualityService
from services.storage_service import StorageService

logger = get_logger("VideoService")

# Editing intensity -> Ken Burns zoom ceiling ("balanced" == previous default)
ZOOM_BY_INTENSITY = {"calm": 1.05, "balanced": settings.ZOOM_INTENSITY, "dynamic": 1.18}


class _Timer:
    """Wall-clock time per pipeline stage (stored in the job report, so slowness is always visible)."""

    def __init__(self) -> None:
        self.times: dict = {}
        self._t = time.perf_counter()

    def mark(self, name: str) -> None:
        now = time.perf_counter()
        self.times[name] = round(now - self._t, 2)
        self._t = now


class VideoService:
    """
    Orchestrates the full video generation pipeline.
    Called from the Celery worker task.
    """

    def __init__(
        self,
        job_service: JobService,
        storage_service: StorageService,
    ) -> None:
        self.job_service = job_service
        self.storage_service = storage_service

        # Instantiate all agents once — they're stateless between runs
        self.segmentation_agent = ScriptSegmentationAgent()
        self.mapping_agent = SceneMappingAgent()
        self.analyzer = VideoAnalyzer()
        self.vision_agent = VisionAgent()
        self.engine = EditingEngine()
        self.plan_agent = EditingPlanAgent()
        self.quality = QualityService()
        self.audio_agent = AudioGenerationAgent()
        self.subtitle_agent = SubtitleTimingAgent()
        self.composition_agent = VideoCompositionAgent()

    @classmethod
    def create(cls) -> "VideoService":
        return cls(
            job_service=JobService.create(),
            storage_service=StorageService.create(),
        )

    # ── Main pipeline ─────────────────────────────────────────────────────────

    def process_job(self, job_id: str) -> str:
        """
        Run the full pipeline for a job.
        Returns the path of the final MP4 on success.
        Marks job as FAILED on any exception.
        """
        logger.info(f"═══ Starting pipeline for job {job_id} ═══")

        try:
            job = self.job_service.get_job(job_id)
            output_dir = self.job_service.get_job_output_dir(job_id)

            style = R.get_style(job.editing_style.value)
            tm = _Timer()

            # ── Stage 1: Media analysis (deterministic, cached per clip) ──────
            self._update(job, "Analyzing your clips", 8)
            analyses, usable_clips, dropped = self._analyze(job)
            tm.mark("analysis")

            # ── Stage 2: Script segmentation (+ role/intent/energy, no LLM) ───
            self._update(job, "Segmenting script into scenes", 20)
            scenes = self.segmentation_agent.run(script=job.script)
            job.scenes = scenes
            self.job_service.update_job(job)
            logger.info(f"  → {len(scenes)} scenes extracted")
            tm.mark("script")

            # ── Stage 3: Edit plan = rules engine, optional AI refinement, validation ──
            self._update(job, "Planning the edit", 28)
            scene_mappings = self._make_plan(job, scenes, analyses, usable_clips)
            job.scene_mappings = scene_mappings
            self.job_service.update_job(job)
            tm.mark("plan")
            logger.info(f"  → {len(scene_mappings)} planned shots ({scene_mappings[0].planned_by if scene_mappings else '-'})")

            # ── Stage 4: Audio Generation (real narration length drives timing) ──
            self._update(job, "Generating AI voiceover", 42)
            audio_result = self.audio_agent.run(
                scenes=scenes,
                output_dir=output_dir,
                tts_provider=job.tts_provider,
                job_id=job_id,
            )
            job.audio_result = audio_result
            self.job_service.update_job(job)
            logger.info(f"  → Audio: {audio_result.duration:.1f}s ({audio_result.provider.value}, timings: {audio_result.timing_source})")
            tm.mark("voice")

            # ── Stage 5: Fit shot lengths to the narration (word timings if available) ──
            scene_mappings = validate_plan(retime_plan(scene_mappings, scenes, audio_result), analyses)
            job.scene_mappings = scene_mappings
            self.job_service.update_job(job)
            self._save_plan(output_dir, scene_mappings, job, analyses, audio_result)
            tm.mark("timing")

            # ── Stage 6: Subtitle timing (phrase-based) ───────────────────────
            self._update(job, "Generating subtitle timings", 62)
            subtitles = self.subtitle_agent.run(
                audio_result=audio_result,
                scenes=scenes,
                max_words=style.caption_max_words,
            )
            job.subtitles = subtitles
            self.job_service.update_job(job)
            logger.info(f"  → {len(subtitles)} subtitle entries")
            tm.mark("subtitles")

            # ── Stage 7: Video Composition ────────────────────────────────────
            self._update(job, "Compositing video (FFmpeg)", 75)
            final_path = self.composition_agent.run(
                scene_mappings=scene_mappings,
                audio_result=audio_result,
                subtitles=subtitles,
                output_dir=output_dir,
                job_id=job_id,
                transition=job.transition,
                zoom=ZOOM_BY_INTENSITY.get(job.intensity.value),
                subtitle_position=job.subtitle_position.value,
                caption_style=job.caption_style.value,
                should_cancel=lambda: self._check_cancel(job_id),
                caption_punch=style.caption_punch,
                caption_zones=caption_zones(scene_mappings, job.subtitle_position.value),
            )
            logger.info(f"  → Final video: {final_path}")
            tm.mark("compose")

            # ── Stage 8: Technical validation of the rendered file ────────────
            self._update(job, "Checking the finished video", 94)
            report = self.quality.check(
                final_path,
                expected_duration=audio_result.duration,
                plan_duration=sum(m.duration or 0 for m in scene_mappings) - sum(m.join_dur for m in scene_mappings[:-1]),
                subtitle_count=len(subtitles),
                captions_expected=True,
            )
            tm.mark("validate")
            report["timings"] = {**tm.times, "total": round(sum(tm.times.values()), 2)}
            report["voice"] = {"provider": audio_result.provider.value, "fallback_used": audio_result.fallback_used,
                               "timing_source": audio_result.timing_source}
            report["warnings"] = list(report.get("warnings", [])) + audio_result.warnings + dropped
            try:
                Path(output_dir, "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            except OSError:
                pass

            # ── Finalise ───────────────────────────────────────────────────
            output_url = self.storage_service.get_output_url(
                job_id, Path(final_path).name
            )
            self.job_service.mark_completed(job_id, final_path, output_url)
            self._store_report(job_id, report)

            # Clean up intermediate work files
            self.storage_service.cleanup_work_files(job_id)
            self.storage_service.cleanup_uploads(job_id)

            logger.info(f"═══ Job {job_id} COMPLETED → {final_path} ═══")
            return final_path

        except JobCancelledError:
            logger.info(f"Job {job_id} cancelled by user")
            self.job_service.mark_cancelled(job_id)
            self.storage_service.cleanup_work_files(job_id)
            self.storage_service.cleanup_uploads(job_id)
            return ""
        except VideoGenBaseError as exc:
            logger.error(f"Pipeline error for {job_id}: {exc.message}")
            self.job_service.mark_failed(job_id, exc.message)
            raise
        except Exception as exc:
            logger.error(f"Unexpected error for {job_id}: {exc}", exc_info=True)
            self.job_service.mark_failed(job_id, str(exc))
            raise

    # ── Internal helpers ──────────────────────────────────────────────────────

    # ── Planning helpers ──────────────────────────────────────────────────────

    def _analyze(self, job: Job):
        """Analyse clips (cached, parallel). Unreadable or missing clips are dropped, not fatal."""
        analyses: dict = {}
        try:
            analyses = self.analyzer.run(clip_paths=job.clip_paths)
        except Exception as exc:                       # analysis must never fail a job
            logger.warning(f"  → analysis failed, continuing without it: {exc}")
        try:
            analyses = self.vision_agent.run(analyses=analyses) or analyses   # no-op unless VISION_ENABLED
        except Exception as exc:
            logger.warning(f"  → vision step skipped: {exc}")
        if not analyses:                               # analyzer unavailable: trust the upload list
            return analyses, list(job.clip_paths), []
        usable = [p for p in job.clip_paths if p in analyses and analyses[p].width > 0 and analyses[p].duration > 0.3]
        dropped = [f"Skipped an unreadable clip: {Path(p).name.split('-', 1)[-1]}" for p in job.clip_paths if p not in usable]
        if dropped:
            logger.warning(f"  → {len(dropped)} clip(s) unreadable and skipped")
        if not usable:
            raise VideoCompositionError("None of your clips could be read. Check they are valid video files.")
        return analyses, usable, dropped

    def _make_plan(self, job: Job, scenes, analyses, clips) -> list:
        """Rules first (always), AI second (optional), validation last."""
        override = job.transition_override.value if job.transition_override else None
        try:
            plan = self.engine.run(
                scenes=scenes, analyses=analyses, clip_paths=clips,
                style=job.editing_style.value, intensity=job.intensity, transition_override=override,
            )
        except Exception as exc:
            logger.warning(f"  → editing engine failed, using basic clip mapping: {exc}")
            return self.mapping_agent.run(scenes=scenes, clip_paths=clips)   # legacy, always works
        try:
            plan = self.plan_agent.run(
                scenes=scenes, plan=plan, analyses=analyses,
                style=job.editing_style.value, intensity=job.intensity,
            )
        except Exception as exc:
            logger.warning(f"  → AI planner skipped: {exc}")
        return validate_plan(plan, analyses)

    def _save_plan(self, output_dir, plan, job: Job, analyses, audio) -> None:
        try:
            extra = {
                "planner": "ai" if any(m.planned_by == "ai" for m in plan) else "rules",
                "audio": {"duration": round(audio.duration, 2), "word_timings": bool(audio.word_timings), "provider": getattr(audio.provider, "value", str(audio.provider))},
                "clips": [{"name": Path(p).name, "duration": a.duration, "orientation": a.orientation,
                           "quality": a.quality_score, "motion": a.motion_score, "camera": a.camera_motion,
                           "cuts": a.scene_changes, "usable": a.usable_ranges, "best": a.best_segments,
                           "subject": a.subject, "degraded": a.degraded,
                           "tags": (a.visual or {}).get("tags", [])} for p, a in analyses.items()],
            }
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            Path(output_dir, "plan.json").write_text(
                json.dumps(plan_to_json(plan, job.editing_style.value, extra), indent=2), encoding="utf-8")
        except Exception as exc:                       # a debugging aid must never fail the job
            logger.warning(f"  → could not save plan.json: {exc}")

    def _store_report(self, job_id: str, report: dict) -> None:
        try:
            j = self.job_service.get_job(job_id)
            j.report = report
            self.job_service.update_job(j)
        except Exception as exc:
            logger.warning(f"  → could not attach report to job: {exc}")

    def _check_cancel(self, job_id: str) -> None:
        if self.job_service.is_cancel_requested(job_id):
            raise JobCancelledError("Cancelled by user.")

    def _update(self, job: Job, stage: str, progress: int) -> None:
        """Update the job's stage + progress in storage (and honour cancel requests)."""
        self._check_cancel(job.job_id)
        job.set_stage(stage, progress)
        job.status = JobStatus.PROCESSING
        self.job_service.update_job(job)
        logger.info(f"  [{progress}%] {stage}")
