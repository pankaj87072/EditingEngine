"""
services/job_service.py
------------------------
JobService
----------
Handles all job CRUD operations.
Jobs are stored as JSON files in ./data/outputs/{job_id}/job.json.
This can be swapped for a database (Redis, Postgres) without touching
any agent or route code — the interface stays the same.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Optional

from core.config import settings
from core.exceptions import JobNotFoundError, StorageError
from core.logging import get_logger
from models.schema import Job, JobStatus

logger = get_logger("JobService")

_JOB_ID_RE = re.compile(r"[0-9a-fA-F-]{36}")


class JobService:
    """
    CRUD for Job objects.
    Thread-safe reads are fine; writes use atomic file replace.
    """

    # ── Factory / DI ──────────────────────────────────────────────────────────

    @classmethod
    def create(cls) -> "JobService":
        return cls()

    # ── Public API ────────────────────────────────────────────────────────────

    def create_job(self, job: Job) -> Job:
        """Persist a new job. Raises StorageError on failure."""
        job_dir = self._job_dir(job.job_id)
        try:
            job_dir.mkdir(parents=True, exist_ok=True)
            self._write(job)
            logger.info(f"Created job {job.job_id}")
            return job
        except Exception as exc:
            raise StorageError(f"Could not create job {job.job_id}: {exc}") from exc

    def get_job(self, job_id: str) -> Job:
        """Load and return a Job. Raises JobNotFoundError if missing."""
        path = self._job_path(job_id)
        if not path.exists():
            raise JobNotFoundError(f"Job '{job_id}' not found.")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Job(**data)
        except Exception as exc:
            raise StorageError(
                f"Could not read job {job_id}: {exc}"
            ) from exc

    def update_job(self, job: Job) -> Job:
        """Overwrite the stored job with the updated version."""
        path = self._job_path(job.job_id)
        if not path.exists():
            raise JobNotFoundError(f"Job '{job.job_id}' not found.")
        job.touch()
        self._write(job)
        return job

    def set_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        progress: int = 0,
        stage: str = "",
        error: Optional[str] = None,
    ) -> Job:
        """Convenience updater for status + progress."""
        job = self.get_job(job_id)
        job.status = status
        job.progress = progress
        job.current_stage = stage
        if error is not None:
            job.error = error
        return self.update_job(job)

    def mark_completed(self, job_id: str, output_path: str, output_url: str) -> Job:
        job = self.get_job(job_id)
        job.status = JobStatus.COMPLETED
        job.progress = 100
        job.current_stage = "completed"
        job.output_path = output_path
        job.output_url = output_url
        return self.update_job(job)

    def mark_failed(self, job_id: str, error: str) -> Job:
        job = self.get_job(job_id)
        job.status = JobStatus.FAILED
        job.current_stage = "failed"
        job.error = error
        return self.update_job(job)

    def list_jobs(self, owner_id: Optional[str] = None, restrict: bool = False, limit: int = 200) -> list:
        """Newest first. With restrict=True only jobs owned by owner_id are returned."""
        jobs = []
        if not settings.OUTPUTS_DIR.exists():
            return jobs
        for d in settings.OUTPUTS_DIR.iterdir():
            if not (_JOB_ID_RE.fullmatch(d.name) and (d / "job.json").exists()):
                continue
            try:
                job = self.get_job(d.name)
            except Exception:
                continue
            if restrict and job.owner_id != owner_id:
                continue
            jobs.append(job)
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def request_cancel(self, job_id: str) -> None:
        self.get_job(job_id)  # 404 if missing
        (self._job_dir(job_id) / "CANCEL").touch()

    def is_cancel_requested(self, job_id: str) -> bool:
        return (self._job_dir(job_id) / "CANCEL").exists()

    def mark_cancelled(self, job_id: str) -> Job:
        job = self.get_job(job_id)
        job.status = JobStatus.CANCELLED
        job.current_stage = "cancelled"
        job.error = None
        return self.update_job(job)

    def delete_job(self, job_id: str) -> None:
        """Remove a job's record, output video and any leftover uploads."""
        if not _JOB_ID_RE.fullmatch(job_id):
            raise JobNotFoundError(f"Job '{job_id}' not found.")
        job_dir = self._job_dir(job_id)
        if not job_dir.exists():
            raise JobNotFoundError(f"Job '{job_id}' not found.")
        shutil.rmtree(job_dir, ignore_errors=True)
        shutil.rmtree(settings.UPLOADS_DIR / job_id, ignore_errors=True)
        logger.info(f"Deleted job {job_id}")

    def get_job_output_dir(self, job_id: str) -> str:
        """Return the output directory for a job, creating it if needed."""
        d = self._job_dir(job_id)
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _job_dir(self, job_id: str) -> Path:
        return settings.OUTPUTS_DIR / job_id

    def _job_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "job.json"

    def _write(self, job: Job) -> None:
        """Serialise job to JSON and write atomically."""
        path = self._job_path(job.job_id)
        # Write to temp then rename for atomic update
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            job.model_dump_json(indent=2),
            encoding="utf-8",
        )
        tmp.rename(path)
