"""
api/routes/video_routes.py
---------------------------
FastAPI route handlers for the video generation API.

Routes:
    POST /generate          — upload script + clips, returns job_id
    GET  /status/{job_id}   — returns processing status + progress
    GET  /result/{job_id}   — returns video URL on completion
    GET  /result/{job_id}/download — streams the final MP4
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from api.deps import current_user
from core.config import settings
from core.exceptions import (
    JobNotFoundError,
    StorageError,
    UnsupportedFileTypeError,
    ValidationError,
)
from core.logging import get_logger
from core.editing_rules import get_style
from models.schema import (
    EditingStyle,
    CaptionStyle,
    EditingIntensity,
    SubtitlePosition,
    Job,
    JobCreateResponse,
    JobResultResponse,
    JobStatus,
    JobStatusResponse,
    TransitionType,
    TTSProvider,
)
from services.job_service import JobService
from services.storage_service import StorageService

logger = get_logger("VideoRoutes")

router = APIRouter(prefix="", tags=["Video Generation"])

# ── Dependency instances (swap for DI container if needed) ────────────────────
_job_service = JobService.create()
_storage_service = StorageService.create()


# ── POST /generate ────────────────────────────────────────────────────────────

@router.post(
    "/generate",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a new video generation job",
    description=(
        "Upload a script and 1–10 short video clips. "
        "Returns a job_id you can use to poll /status/{job_id}."
    ),
)
async def generate_video(
    script: str = Form(..., description="Full narration script text"),
    tts_provider: TTSProvider = Form(
        TTSProvider.AUTO,
        description="Voice: 'auto' (ElevenLabs if configured, else Google), 'elevenlabs' or 'google'",
    ),
    transition: Optional[TransitionType] = Form(
        None,
        description="LEGACY override: 'none', 'fade', 'crossfade' or 'zoom'. Leave empty: the editing style decides.",
    ),
    editing_style: EditingStyle = Form(
        EditingStyle.CLEAN,
        description="clean | social_punchy | cinematic | dynamic | storytelling | product_focus",
    ),
    subtitle_position: SubtitlePosition = Form(
        SubtitlePosition.BOTTOM, description="Caption position: 'bottom' or 'center'"
    ),
    caption_style: CaptionStyle = Form(
        CaptionStyle.CLASSIC, description="Caption look: 'classic', 'bold' or 'soft'"
    ),
    intensity: EditingIntensity = Form(
        EditingIntensity.BALANCED, description="Camera movement: 'calm', 'balanced' or 'dynamic'"
    ),
    uid: Optional[str] = Depends(current_user),
    clips: List[UploadFile] = File(
        ...,
        description="1–10 short video clips (MP4, MOV, AVI, MKV)",
    ),
):
    print(f"Received job request...")
    print(f"Received job request | script_length={len(script)} | "
          f"tts_provider={tts_provider} | transition={transition} | "
          f"num_clips={len(clips)}")
    # ── Validate inputs ───────────────────────────────────────────────────────
    if not script.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Script text cannot be empty.",
        )

    if not clips:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one video clip must be uploaded.",
        )

    if len(clips) > 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Maximum 10 video clips allowed.",
        )

    # ── Create job record ─────────────────────────────────────────────────────
    job_id = str(uuid.uuid4())
    job = Job(
        job_id=job_id,
        script=script,
        tts_provider=tts_provider,
        transition=transition or TransitionType(get_style(editing_style.value).legacy_transition),
        transition_override=transition,
        editing_style=editing_style,
        subtitle_position=subtitle_position,
        caption_style=caption_style,
        intensity=intensity,
        owner_id=uid,
    )

    try:
        _job_service.create_job(job)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create job: {exc.message}",
        )

    # ── Save uploaded clips ───────────────────────────────────────────────────
    clip_paths: List[str] = []
    for clip_file in clips:
        try:
            data = await clip_file.read()
            path = _storage_service.save_upload(
                job_id=job_id,
                filename=Path(clip_file.filename or "").name or f"clip_{len(clip_paths)}.mp4",
                data=data,
            )
            clip_paths.append(path)
        except UnsupportedFileTypeError as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=exc.message,
            )
        except StorageError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=exc.message,
            )

    # Persist clip paths on the job
    job.clip_paths = clip_paths
    _job_service.update_job(job)

    # ── Enqueue processing task ───────────────────────────────────────────────
    print(f"Enqueuing job {job_id} for processing...")
    _enqueue_job(job_id)

    logger.info(
        f"Job {job_id} created | "
        f"clips={len(clip_paths)} | "
        f"tts={tts_provider} | "
        f"transition={transition}"
    )

    return JobCreateResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        message=(
            f"Job {job_id} created. "
            f"Poll GET /status/{job_id} for progress."
        ),
    )


# ── GET /status/{job_id} ──────────────────────────────────────────────────────

@router.get(
    "/status/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job processing status",
)
async def get_status(job_id: str, uid: Optional[str] = Depends(current_user)):
    try:
        job = _owned_job(job_id, uid)
    except JobNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )

    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        current_stage=job.current_stage,
        created_at=job.created_at,
        updated_at=job.updated_at,
        error=job.error,
    )


# ── GET /result/{job_id} ──────────────────────────────────────────────────────

@router.get(
    "/result/{job_id}",
    response_model=JobResultResponse,
    summary="Get the result URL for a completed job",
)
async def get_result(job_id: str, uid: Optional[str] = Depends(current_user)):
    try:
        job = _owned_job(job_id, uid)
    except JobNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )

    if job.status == JobStatus.PENDING:
        return JobResultResponse(
            job_id=job_id,
            status=job.status,
            message="Job is queued. Processing has not started yet.",
        )

    if job.status == JobStatus.PROCESSING:
        return JobResultResponse(
            job_id=job_id,
            status=job.status,
            message=f"Processing: {job.current_stage} ({job.progress}%)",
        )

    if job.status == JobStatus.FAILED:
        return JobResultResponse(
            job_id=job_id,
            status=job.status,
            message=f"Job failed: {job.error}",
        )

    if job.status == JobStatus.CANCELLED:
        return JobResultResponse(
            job_id=job_id,
            status=job.status,
            message="Job was cancelled.",
        )

    # COMPLETED
    return JobResultResponse(
        job_id=job_id,
        status=job.status,
        output_url=job.output_url,
        report=job.report,
        message="Video is ready. Use the output_url to download.",
    )


# ── GET /result/{job_id}/download ─────────────────────────────────────────────

@router.get(
    "/result/{job_id}/download",
    summary="Download the final MP4",
    response_class=FileResponse,
)
async def download_result(job_id: str, uid: Optional[str] = Depends(current_user)):
    try:
        job = _owned_job(job_id, uid)
    except JobNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )

    if job.status != JobStatus.COMPLETED or not job.output_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Video is not ready yet. Check /status/{job_id}.",
        )

    output_path = Path(job.output_path)
    if not output_path.exists():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Output file has been removed from server.",
        )

    return FileResponse(
        path=str(output_path),
        media_type="video/mp4",
        filename=f"{job_id}_video.mp4",
    )


# ── GET /result/{job_id}/stream ───────────────────────────────────────────────

@router.get(
    "/result/{job_id}/stream",
    summary="Stream the final MP4 inline (supports Range requests for seeking)",
)
async def stream_result(job_id: str, request: Request, uid: Optional[str] = Depends(current_user)):
    try:
        job = _owned_job(job_id, uid)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    if job.status != JobStatus.COMPLETED or not job.output_path:
        raise HTTPException(status_code=409, detail="Video is not ready yet.")
    path = Path(job.output_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="Output file has been removed from server.")
    return _ranged_file_response(path, request.headers.get("range"))


def _ranged_file_response(path: Path, range_header: Optional[str]) -> Response:
    """Minimal single-range support (the installed Starlette FileResponse has none)."""
    size = path.stat().st_size
    start, end, code = 0, size - 1, 200
    if range_header:
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
        if not m or not (m.group(1) or m.group(2)):
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        if m.group(1) == "":                       # suffix range: last N bytes
            start = max(size - int(m.group(2)), 0)
        else:
            start = int(m.group(1))
            if m.group(2):
                end = min(int(m.group(2)), size - 1)
        if start > end or start >= size:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        code = 206

    def _iter():
        with open(path, "rb") as fh:
            fh.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = fh.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1)}
    if code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(_iter(), status_code=code, media_type="video/mp4", headers=headers)


def _owned_job(job_id: str, uid: Optional[str]):
    """get_job + ownership check. Someone else's job looks like a missing job."""
    job = _job_service.get_job(job_id)
    if settings.AUTH_ENABLED and job.owner_id != uid:
        raise JobNotFoundError(f"Job '{job_id}' not found.")
    return job


# ── GET /jobs ─────────────────────────────────────────────────────────────────

@router.get("/jobs", summary="List your jobs, newest first (powers History)")
async def list_jobs(uid: Optional[str] = Depends(current_user)):
    jobs = _job_service.list_jobs(owner_id=uid, restrict=settings.AUTH_ENABLED)
    return {
        "jobs": [
            {
                "job_id": j.job_id,
                "status": j.status,
                "progress": j.progress,
                "current_stage": j.current_stage,
                "created_at": j.created_at,
                "updated_at": j.updated_at,
                "error": j.error,
                "script": j.script,
                "clip_count": len(j.clip_paths),
                "tts_provider": j.tts_provider,
                "transition": j.transition,
                "editing_style": j.editing_style,
                "intensity": j.intensity,
                "caption_style": j.caption_style,
                "subtitle_position": j.subtitle_position,
            }
            for j in jobs
        ]
    }


# ── GET /result/{job_id}/plan ─────────────────────────────────────────────────

@router.get(
    "/result/{job_id}/plan",
    summary="The editing plan used for this Reel (scene -> clip, start/end, crop, zoom, emphasis)",
)
async def get_plan(job_id: str, uid: Optional[str] = Depends(current_user)):
    try:
        _owned_job(job_id, uid)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    plan_file = Path(_job_service.get_job_output_dir(job_id)) / "plan.json"
    if not plan_file.exists():
        raise HTTPException(status_code=409, detail="The editing plan is not ready yet.")
    return json.loads(plan_file.read_text(encoding="utf-8"))


# ── POST /jobs/{job_id}/cancel ────────────────────────────────────────────────

@router.post(
    "/jobs/{job_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask a running job to stop (takes effect between pipeline steps)",
)
async def cancel_job(job_id: str, uid: Optional[str] = Depends(current_user)):
    try:
        job = _owned_job(job_id, uid)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    if job.status not in (JobStatus.PENDING, JobStatus.PROCESSING):
        raise HTTPException(status_code=409, detail="Job is not running.")
    _job_service.request_cancel(job_id)
    return {"job_id": job_id, "status": job.status, "message": "Cancel requested."}


# ── DELETE /jobs/{job_id} ─────────────────────────────────────────────────────

_STALE_AFTER = timedelta(minutes=30)


@router.delete(
    "/jobs/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a job and its video",
)
async def delete_job(job_id: str, uid: Optional[str] = Depends(current_user)):
    try:
        job = _owned_job(job_id, uid)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    active = job.status in (JobStatus.PENDING, JobStatus.PROCESSING)
    if active and datetime.utcnow() - job.updated_at < _STALE_AFTER:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job is still being processed.",
        )
    _job_service.delete_job(job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Task dispatch helper ──────────────────────────────────────────────────────

# def _enqueue_job(job_id: str) -> None:
#     """
#     Try Celery first. Fall back to background thread worker
#     if Celery / Redis is not available.
#     """
#     try:
#         from workers.celery_app import process_video_job
#         print("using Celery worker for job:", job_id)
#         process_video_job.delay(job_id)
#         logger.info(f"Job {job_id} enqueued via Celery")
#     except Exception as exc:
#         logger.warning(
#             f"Celery unavailable ({exc}). "
#             f"Falling back to background thread worker."
#         )
#         from workers.background_worker import get_background_worker
#         print('Using background worker for job:', job_id)
#         get_background_worker().enqueue(job_id)
#         logger.info(f"Job {job_id} enqueued via BackgroundWorker")

def _enqueue_job(job_id: str) -> None:
    """
    Try Celery first. Fall back to background thread worker
    if Celery / Redis is not available.
    """
    try:
        logger.warning(
            f"Falling back to background thread worker."
        )
        from workers.background_worker import get_background_worker
        print('Using background worker for job:', job_id)
        get_background_worker().enqueue(job_id)
        logger.info(f"Job {job_id} enqueued via BackgroundWorker")
    except Exception as exc:
        print('error occured',exc)
        raise HTTPException(status = 404,detail="Background worker cant load")
        
