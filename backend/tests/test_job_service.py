"""
tests/test_job_service.py
--------------------------
Unit tests for JobService.
Uses tmp_path so no real ./data/ directory is touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.exceptions import JobNotFoundError, StorageError
from models.schema import Job, JobStatus, TransitionType, TTSProvider
from services.job_service import JobService


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def service(tmp_path) -> JobService:
    """JobService that stores data in a temporary directory."""
    svc = JobService()
    # Patch the outputs dir to our temp path so we don't pollute real storage
    with patch("services.job_service.settings") as mock_settings:
        mock_settings.OUTPUTS_DIR = tmp_path
        yield svc


@pytest.fixture
def sample_job() -> Job:
    return Job(
        script="This is a test script for the job service unit tests.",
        tts_provider=TTSProvider.GOOGLE,
        transition=TransitionType.FADE,
        clip_paths=["/tmp/clip1.mp4", "/tmp/clip2.mp4"],
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCreateJob:
    def test_creates_json_file_on_disk(self, tmp_path, sample_job):
        svc = JobService()
        with patch("services.job_service.settings") as m:
            m.OUTPUTS_DIR = tmp_path
            svc.create_job(sample_job)

        job_file = tmp_path / sample_job.job_id / "job.json"
        assert job_file.exists()

    def test_persisted_data_is_valid_json(self, tmp_path, sample_job):
        svc = JobService()
        with patch("services.job_service.settings") as m:
            m.OUTPUTS_DIR = tmp_path
            svc.create_job(sample_job)

        job_file = tmp_path / sample_job.job_id / "job.json"
        data = json.loads(job_file.read_text())
        assert data["job_id"] == sample_job.job_id
        assert data["status"] == "pending"

    def test_returns_job_object(self, tmp_path, sample_job):
        svc = JobService()
        with patch("services.job_service.settings") as m:
            m.OUTPUTS_DIR = tmp_path
            result = svc.create_job(sample_job)

        assert isinstance(result, Job)
        assert result.job_id == sample_job.job_id


class TestGetJob:
    def test_get_existing_job(self, tmp_path, sample_job):
        svc = JobService()
        with patch("services.job_service.settings") as m:
            m.OUTPUTS_DIR = tmp_path
            svc.create_job(sample_job)
            loaded = svc.get_job(sample_job.job_id)

        assert loaded.job_id == sample_job.job_id
        assert loaded.script == sample_job.script

    def test_get_nonexistent_job_raises(self, tmp_path):
        svc = JobService()
        with patch("services.job_service.settings") as m:
            m.OUTPUTS_DIR = tmp_path
            with pytest.raises(JobNotFoundError):
                svc.get_job("does-not-exist-at-all")


class TestUpdateJob:
    def test_update_persists_changes(self, tmp_path, sample_job):
        svc = JobService()
        with patch("services.job_service.settings") as m:
            m.OUTPUTS_DIR = tmp_path
            svc.create_job(sample_job)

            sample_job.status = JobStatus.PROCESSING
            sample_job.progress = 42
            svc.update_job(sample_job)

            reloaded = svc.get_job(sample_job.job_id)

        assert reloaded.status == JobStatus.PROCESSING
        assert reloaded.progress == 42

    def test_update_nonexistent_raises(self, tmp_path):
        svc = JobService()
        ghost_job = Job(script="ghost")
        with patch("services.job_service.settings") as m:
            m.OUTPUTS_DIR = tmp_path
            with pytest.raises(JobNotFoundError):
                svc.update_job(ghost_job)


class TestMarkCompleted:
    def test_sets_completed_status(self, tmp_path, sample_job):
        svc = JobService()
        with patch("services.job_service.settings") as m:
            m.OUTPUTS_DIR = tmp_path
            svc.create_job(sample_job)
            svc.mark_completed(
                sample_job.job_id,
                output_path="/tmp/final.mp4",
                output_url="/result/test/download",
            )
            job = svc.get_job(sample_job.job_id)

        assert job.status == JobStatus.COMPLETED
        assert job.progress == 100
        assert job.output_path == "/tmp/final.mp4"
        assert job.output_url == "/result/test/download"


class TestMarkFailed:
    def test_sets_failed_status_with_error(self, tmp_path, sample_job):
        svc = JobService()
        with patch("services.job_service.settings") as m:
            m.OUTPUTS_DIR = tmp_path
            svc.create_job(sample_job)
            svc.mark_failed(sample_job.job_id, "FFmpeg exploded")
            job = svc.get_job(sample_job.job_id)

        assert job.status == JobStatus.FAILED
        assert "FFmpeg exploded" in job.error


class TestGetJobOutputDir:
    def test_creates_directory(self, tmp_path, sample_job):
        svc = JobService()
        with patch("services.job_service.settings") as m:
            m.OUTPUTS_DIR = tmp_path
            out_dir = svc.get_job_output_dir(sample_job.job_id)

        assert Path(out_dir).exists()
