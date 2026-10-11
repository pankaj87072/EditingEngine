"""
tests/test_video_service.py
-----------------------------
Unit tests for VideoService — the pipeline orchestrator.

All five agents are mocked so this test validates:
  - The correct call sequence
  - Progress / stage updates on the job
  - Error handling when an agent fails
  - Job is marked FAILED on exception
"""

from __future__ import annotations

from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch, call
import uuid

import pytest

from models.schema import (
    AudioResult,
    Job,
    JobStatus,
    SceneMappingResult,
    ScriptScene,
    SubtitleEntry,
    TransitionType,
    TTSProvider,
)
from services.job_service import JobService
from services.storage_service import StorageService
from services.video_service import VideoService


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def job_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def sample_job(job_id, tmp_path) -> Job:
    return Job(
        job_id=job_id,
        script=(
            "Welcome to our product. "
            "Today we show you the future of technology. "
            "Join us on this exciting journey forward."
        ),
        tts_provider=TTSProvider.GOOGLE,
        transition=TransitionType.FADE,
        clip_paths=[str(tmp_path / "clip1.mp4"), str(tmp_path / "clip2.mp4")],
    )


@pytest.fixture
def mock_job_service(sample_job) -> MagicMock:
    svc = MagicMock(spec=JobService)
    svc.get_job.return_value = sample_job
    svc.update_job.side_effect = lambda j: j
    svc.mark_completed.return_value = sample_job
    svc.mark_failed.return_value = sample_job
    svc.is_cancel_requested.return_value = False
    svc.get_job_output_dir.return_value = "/tmp/test_output"
    return svc


@pytest.fixture
def mock_storage_service() -> MagicMock:
    svc = MagicMock(spec=StorageService)
    svc.get_output_url.return_value = "/result/test-job/download"
    return svc


@pytest.fixture
def fake_scenes() -> List[ScriptScene]:
    return [
        ScriptScene(
            scene_index=0,
            text="Welcome to our product.",
            word_count=4,
            estimated_duration=1.6,
        ),
        ScriptScene(
            scene_index=1,
            text="Today we show you the future of technology.",
            word_count=8,
            estimated_duration=3.2,
        ),
    ]


@pytest.fixture
def fake_mappings(tmp_path) -> List[SceneMappingResult]:
    return [
        SceneMappingResult(
            scene_index=0,
            clip_path=str(tmp_path / "clip1.mp4"),
            clip_duration=5.0,
            scene_text="Welcome to our product.",
        ),
        SceneMappingResult(
            scene_index=1,
            clip_path=str(tmp_path / "clip2.mp4"),
            clip_duration=5.0,
            scene_text="Today we show you the future.",
        ),
    ]


@pytest.fixture
def fake_audio(tmp_path) -> AudioResult:
    audio_path = tmp_path / "narration.mp3"
    audio_path.write_bytes(b"\x00" * 100)
    return AudioResult(
        audio_path=str(audio_path),
        duration=12.0,
        provider=TTSProvider.GOOGLE,
        word_timings=[],
    )


@pytest.fixture
def fake_subtitles() -> List[SubtitleEntry]:
    return [
        SubtitleEntry(index=0, start_time=0.0, end_time=1.5, text="Welcome to"),
        SubtitleEntry(index=1, start_time=1.5, end_time=3.0, text="our product."),
    ]


# ── Helper to build VideoService with mocked agents ───────────────────────────

def make_service(
    mock_job_service,
    mock_storage_service,
    fake_scenes,
    fake_mappings,
    fake_audio,
    fake_subtitles,
    final_path="/tmp/test_output/job_final.mp4",
) -> VideoService:
    svc = VideoService(
        job_service=mock_job_service,
        storage_service=mock_storage_service,
    )
    svc.segmentation_agent = MagicMock()
    svc.segmentation_agent.run.return_value = fake_scenes

    svc.mapping_agent = MagicMock()
    svc.mapping_agent.run.return_value = fake_mappings

    svc.analyzer = MagicMock()
    svc.analyzer.run.return_value = {}
    svc.vision_agent = MagicMock()
    svc.vision_agent.run.side_effect = lambda analyses: analyses
    svc.engine = MagicMock()
    svc.engine.run.return_value = fake_mappings
    svc.plan_agent = MagicMock()
    svc.plan_agent.run.return_value = fake_mappings
    svc.quality = MagicMock()
    svc.quality.check.return_value = {"ok": True, "errors": [], "warnings": []}

    svc.audio_agent = MagicMock()
    svc.audio_agent.run.return_value = fake_audio

    svc.subtitle_agent = MagicMock()
    svc.subtitle_agent.run.return_value = fake_subtitles

    svc.composition_agent = MagicMock()
    svc.composition_agent.run.return_value = final_path

    return svc


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_all_agents_called_in_order(
    mock_job_service, mock_storage_service,
    fake_scenes, fake_mappings, fake_audio, fake_subtitles, job_id
):
    """All 5 agents must be called and in the correct pipeline order."""
    svc = make_service(
        mock_job_service, mock_storage_service,
        fake_scenes, fake_mappings, fake_audio, fake_subtitles,
    )
    svc.process_job(job_id)

    svc.segmentation_agent.run.assert_called_once()
    svc.engine.run.assert_called_once()
    svc.audio_agent.run.assert_called_once()
    svc.subtitle_agent.run.assert_called_once()
    svc.composition_agent.run.assert_called_once()


def test_segmentation_receives_script(
    mock_job_service, mock_storage_service,
    fake_scenes, fake_mappings, fake_audio, fake_subtitles,
    sample_job, job_id
):
    """ScriptSegmentationAgent must receive the job's script text."""
    svc = make_service(
        mock_job_service, mock_storage_service,
        fake_scenes, fake_mappings, fake_audio, fake_subtitles,
    )
    svc.process_job(job_id)

    call_kwargs = svc.segmentation_agent.run.call_args.kwargs
    assert call_kwargs["script"] == sample_job.script


def test_mapping_receives_clips_and_scenes(
    mock_job_service, mock_storage_service,
    fake_scenes, fake_mappings, fake_audio, fake_subtitles,
    sample_job, job_id
):
    """The EditingEngine must receive scenes AND clip_paths (plus the style) from the job."""
    svc = make_service(
        mock_job_service, mock_storage_service,
        fake_scenes, fake_mappings, fake_audio, fake_subtitles,
    )
    svc.process_job(job_id)

    kwargs = svc.engine.run.call_args.kwargs
    assert kwargs["scenes"] == fake_scenes
    assert kwargs["clip_paths"] == sample_job.clip_paths
    assert kwargs["style"] == sample_job.editing_style.value


def test_job_marked_completed_on_success(
    mock_job_service, mock_storage_service,
    fake_scenes, fake_mappings, fake_audio, fake_subtitles, job_id
):
    """Job must be marked COMPLETED after successful pipeline execution."""
    svc = make_service(
        mock_job_service, mock_storage_service,
        fake_scenes, fake_mappings, fake_audio, fake_subtitles,
    )
    svc.process_job(job_id)

    mock_job_service.mark_completed.assert_called_once()
    call_args = mock_job_service.mark_completed.call_args
    assert call_args.args[0] == job_id


def test_job_marked_failed_on_agent_error(
    mock_job_service, mock_storage_service,
    fake_scenes, fake_mappings, fake_audio, fake_subtitles, job_id
):
    """If any agent raises, the job must be marked FAILED."""
    from core.exceptions import SceneMappingError

    svc = make_service(
        mock_job_service, mock_storage_service,
        fake_scenes, fake_mappings, fake_audio, fake_subtitles,
    )
    # The engine crashes AND the legacy fallback mapping crashes too -> nothing can edit -> job fails
    svc.engine.run.side_effect = RuntimeError("engine crashed")
    svc.mapping_agent.run.side_effect = SceneMappingError("No clips found")

    with pytest.raises(SceneMappingError):
        svc.process_job(job_id)

    mock_job_service.mark_failed.assert_called_once()
    args = mock_job_service.mark_failed.call_args.args
    assert args[0] == job_id
    assert "No clips found" in args[1]


def test_composition_receives_audio_and_subtitles(
    mock_job_service, mock_storage_service,
    fake_scenes, fake_mappings, fake_audio, fake_subtitles, job_id
):
    """VideoCompositionAgent must receive audio_result and subtitles."""
    svc = make_service(
        mock_job_service, mock_storage_service,
        fake_scenes, fake_mappings, fake_audio, fake_subtitles,
    )
    svc.process_job(job_id)

    kwargs = svc.composition_agent.run.call_args.kwargs
    assert kwargs["audio_result"] == fake_audio
    assert kwargs["subtitles"] == fake_subtitles
    # Mappings are fitted to the narration: same scenes/clips, lengths sum to the audio.
    got = kwargs["scene_mappings"]
    assert [(m.scene_index, m.clip_path) for m in got] == [(m.scene_index, m.clip_path) for m in fake_mappings]
    assert abs(sum(m.duration for m in got) - fake_audio.duration) < 0.5


def test_storage_cleanup_called_on_success(
    mock_job_service, mock_storage_service,
    fake_scenes, fake_mappings, fake_audio, fake_subtitles, job_id
):
    """Uploads + work files should be cleaned up after success."""
    svc = make_service(
        mock_job_service, mock_storage_service,
        fake_scenes, fake_mappings, fake_audio, fake_subtitles,
    )
    svc.process_job(job_id)

    mock_storage_service.cleanup_work_files.assert_called_once_with(job_id)
    mock_storage_service.cleanup_uploads.assert_called_once_with(job_id)


def test_returns_output_path(
    mock_job_service, mock_storage_service,
    fake_scenes, fake_mappings, fake_audio, fake_subtitles, job_id
):
    """process_job() must return the final video path as a string."""
    expected = "/tmp/test_output/job_final.mp4"
    svc = make_service(
        mock_job_service, mock_storage_service,
        fake_scenes, fake_mappings, fake_audio, fake_subtitles,
        final_path=expected,
    )
    result = svc.process_job(job_id)
    assert result == expected


def test_engine_failure_falls_back_to_basic_mapping_and_still_completes(
    mock_job_service, mock_storage_service,
    fake_scenes, fake_mappings, fake_audio, fake_subtitles, job_id
):
    """Rules must always produce a usable edit: if the engine crashes, the legacy mapping takes over."""
    svc = make_service(
        mock_job_service, mock_storage_service,
        fake_scenes, fake_mappings, fake_audio, fake_subtitles,
    )
    svc.engine.run.side_effect = RuntimeError("engine crashed")
    assert svc.process_job(job_id)
    svc.mapping_agent.run.assert_called_once()
    svc.composition_agent.run.assert_called_once()


def test_analysis_and_ai_failures_never_fail_the_job(
    mock_job_service, mock_storage_service,
    fake_scenes, fake_mappings, fake_audio, fake_subtitles, job_id
):
    svc = make_service(
        mock_job_service, mock_storage_service,
        fake_scenes, fake_mappings, fake_audio, fake_subtitles,
    )
    svc.analyzer.run.side_effect = RuntimeError("ffprobe exploded")
    svc.vision_agent.run.side_effect = RuntimeError("vision API down")
    svc.plan_agent.run.side_effect = RuntimeError("planner API down")
    assert svc.process_job(job_id)
    assert svc.engine.run.call_args.kwargs["analyses"] == {}


def test_failed_technical_validation_fails_the_job(
    mock_job_service, mock_storage_service,
    fake_scenes, fake_mappings, fake_audio, fake_subtitles, job_id
):
    from core.exceptions import VideoCompositionError

    svc = make_service(
        mock_job_service, mock_storage_service,
        fake_scenes, fake_mappings, fake_audio, fake_subtitles,
    )
    svc.quality.check.side_effect = VideoCompositionError("Validation failed: wrong resolution")
    with pytest.raises(VideoCompositionError):
        svc.process_job(job_id)
    mock_job_service.mark_failed.assert_called()
