"""
api/routes/health_routes.py
----------------------------
Health check endpoints.
Used by Docker HEALTHCHECK, load balancers, and monitoring tools.
"""

from __future__ import annotations

import subprocess
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from core.config import settings

router = APIRouter(prefix="/health", tags=["Health"])


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    timestamp: str
    ffmpeg_available: bool
    redis_available: bool


@router.get("", response_model=HealthResponse, summary="System health check")
async def health_check():
    return HealthResponse(
        status="ok",
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        timestamp=datetime.utcnow().isoformat(),
        ffmpeg_available=_check_ffmpeg(),
        redis_available=_check_redis(),
    )


def _check_ffmpeg() -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _check_redis() -> bool:
    try:
        import redis
        r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        r.ping()
        return True
    except Exception:
        return False
