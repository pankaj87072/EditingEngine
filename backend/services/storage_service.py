"""
services/storage_service.py
-----------------------------
StorageService
--------------
Handles saving uploaded files to structured directories.
All upload paths are under ./data/uploads/{job_id}/.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List

from core.config import settings
from core.exceptions import StorageError, UnsupportedFileTypeError
from core.logging import get_logger

logger = get_logger("StorageService")

# Allowed video MIME types / extensions
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


class StorageService:
    """Manages file persistence for uploads and outputs."""

    @classmethod
    def create(cls) -> "StorageService":
        return cls()

    # ── Upload handling ───────────────────────────────────────────────────────

    def save_upload(
        self,
        job_id: str,
        filename: str,
        data: bytes,
    ) -> str:
        """
        Save an uploaded file to ./data/uploads/{job_id}/{filename}.
        Returns the absolute path of the saved file.
        """
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_VIDEO_EXTENSIONS:
            raise UnsupportedFileTypeError(
                f"File '{filename}' has unsupported extension '{ext}'. "
                f"Allowed: {ALLOWED_VIDEO_EXTENSIONS}"
            )

        upload_dir = settings.UPLOADS_DIR / job_id
        upload_dir.mkdir(parents=True, exist_ok=True)

        dest = upload_dir / filename
        try:
            dest.write_bytes(data)
            logger.debug(f"Saved upload: {dest}")
            return str(dest)
        except Exception as exc:
            raise StorageError(f"Could not save {filename}: {exc}") from exc

    def save_uploads_bulk(
        self,
        job_id: str,
        files: List[tuple[str, bytes]],   # (filename, data) pairs
    ) -> List[str]:
        """Save multiple uploaded files. Returns list of saved paths."""
        return [self.save_upload(job_id, fn, data) for fn, data in files]

    # ── Output URL builder ────────────────────────────────────────────────────

    def get_output_url(self, job_id: str, filename: str) -> str:
        """
        Build a URL for accessing a completed output file.
        In production this would point to S3 / CDN.
        """
        return f"/result/{job_id}/download"

    def get_output_path(self, job_id: str, filename: str) -> str:
        return str(settings.OUTPUTS_DIR / job_id / filename)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup_uploads(self, job_id: str) -> None:
        """Remove upload directory after processing is complete."""
        upload_dir = settings.UPLOADS_DIR / job_id
        if upload_dir.exists():
            shutil.rmtree(upload_dir, ignore_errors=True)
            logger.debug(f"Cleaned up uploads for job {job_id}")

    def cleanup_work_files(self, job_id: str) -> None:
        """Remove intermediate work files, keep only final output."""
        work_dir = settings.OUTPUTS_DIR / job_id / "work"
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
            logger.debug(f"Cleaned up work files for job {job_id}")
