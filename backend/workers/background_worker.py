"""
workers/background_worker.py
------------------------------
Lightweight in-process background worker.

Use this as a fallback when Redis / Celery are not available
(e.g., local development, Docker-free environments).

It uses Python's ThreadPoolExecutor to run video jobs in a
background thread — no extra process or broker needed.

Usage in FastAPI (set in main.py based on config):
    from workers.background_worker import BackgroundWorker
    worker = BackgroundWorker()
    worker.enqueue(job_id)
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Dict, Optional

from core.logging import get_logger

logger = get_logger("BackgroundWorker")


class BackgroundWorker:
    """
    Simple thread-pool based task queue.
    Runs at most `max_workers` jobs concurrently.
    """

    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="video-worker",
        )
        self._futures: Dict[str, Future] = {}
        self._lock = threading.Lock()

    def enqueue(self, job_id: str) -> None:
        """Submit a video generation job to the thread pool."""
        # Lazy import avoids circular dependency
        from services.video_service import VideoService

        def _run():
            logger.info(f"[BackgroundWorker] Starting job {job_id}")
            try:
                service = VideoService.create()
                service.process_job(job_id)
                logger.info(f"[BackgroundWorker] Job {job_id} completed")
            except Exception as exc:
                logger.error(
                    f"[BackgroundWorker] Job {job_id} failed: {exc}",
                    exc_info=True,
                )

        with self._lock:
            future = self._executor.submit(_run)
            self._futures[job_id] = future
            logger.info(
                f"[BackgroundWorker] Enqueued job {job_id}. "
                f"Active jobs: {self._active_count()}"
            )

    def is_running(self, job_id: str) -> bool:
        """Check if a job is currently executing."""
        with self._lock:
            future = self._futures.get(job_id)
            return future is not None and future.running()

    def get_future(self, job_id: str) -> Optional[Future]:
        with self._lock:
            return self._futures.get(job_id)

    def shutdown(self, wait: bool = True) -> None:
        """Gracefully shut down the worker pool."""
        logger.info("[BackgroundWorker] Shutting down thread pool...")
        self._executor.shutdown(wait=wait)

    def _active_count(self) -> int:
        return sum(1 for f in self._futures.values() if not f.done())


# ── Singleton for FastAPI app lifetime ───────────────────────────────────────

_worker_instance: Optional[BackgroundWorker] = None


def get_background_worker() -> BackgroundWorker:
    """Return (or create) the singleton BackgroundWorker."""
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = BackgroundWorker()
    return _worker_instance
