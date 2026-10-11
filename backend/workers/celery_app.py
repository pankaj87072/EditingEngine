"""
workers/celery_app.py
----------------------
Celery application factory and task definitions.

The worker is started separately from the FastAPI server:
    celery -A workers.celery_app worker --loglevel=info

Tasks:
    process_video_job(job_id) — the main async video generation task.
"""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_ready
from celery.utils.log import get_task_logger

from core.config import settings
from core.logging import get_logger, setup_logging

# ── Celery app factory ────────────────────────────────────────────────────────

def create_celery_app() -> Celery:
    app = Celery(
        settings.APP_NAME,
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
    )

    app.conf.update(
        # Serialisation
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],

        # Timezone
        timezone="UTC",
        enable_utc=True,

        # Retry / reliability
        task_acks_late=True,               # Ack only after task completes
        task_reject_on_worker_lost=True,   # Re-queue if worker dies mid-task
        worker_prefetch_multiplier=1,      # One task per worker at a time

        # Result TTL — keep results for 24h
        result_expires=86400,

        # Task routes
        task_routes={
            "workers.celery_app.process_video_job": {"queue": "video"},
        },
    )
    return app


celery_app = create_celery_app()
task_logger = get_task_logger(__name__)


# ── Signal: log when worker comes online ─────────────────────────────────────

@worker_ready.connect
def on_worker_ready(sender, **kwargs):
    setup_logging()
    logger = get_logger("CeleryWorker")
    logger.info("✔ Celery worker ready and listening for tasks.")


# ── Main task ─────────────────────────────────────────────────────────────────

@celery_app.task(
    name="workers.celery_app.process_video_job",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    acks_late=True,
)
def process_video_job(self, job_id: str) -> dict:
    """
    Celery task: run the full video generation pipeline for a job.

    Args:
        job_id: The UUID of the job to process.

    Returns:
        dict with keys: job_id, status, output_path
    """
    # Import here to avoid circular imports at module load time
    from services.video_service import VideoService

    task_logger.info(f"Task received: process_video_job(job_id={job_id})")

    try:
        service = VideoService.create()
        final_path = service.process_job(job_id)

        task_logger.info(f"Task completed: {job_id} → {final_path}")
        return {
            "job_id": job_id,
            "status": "completed",
            "output_path": final_path,
        }

    except Exception as exc:
        task_logger.error(f"Task failed: {job_id} — {exc}", exc_info=True)

        # Retry on transient errors (network, TTS API blips)
        # Do NOT retry on validation errors — they won't self-heal
        if self.request.retries < self.max_retries:
            task_logger.warning(
                f"Retrying task {job_id} "
                f"(attempt {self.request.retries + 1}/{self.max_retries})"
            )
            raise self.retry(exc=exc)

        return {
            "job_id": job_id,
            "status": "failed",
            "error": str(exc),
        }
