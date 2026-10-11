"""
api/app.py
-----------
FastAPI application factory.
Creates and configures the ASGI app with middleware, routes, and
global exception handlers.
"""

from __future__ import annotations

import time
import traceback

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes.auth_routes import router as auth_router
from api.routes.health_routes import router as health_router
from api.routes.video_routes import router as video_router

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi import Request

from core.config import settings
from core.exceptions import (
    JobNotFoundError,
    StorageError,
    TTSProviderError,
    ValidationError,
    VideoCompositionError,
    VideoGenBaseError,
)
from core.logging import get_logger, setup_logging

logger = get_logger("App")


def create_app() -> FastAPI:
    """
    Application factory — call this once at startup.
    Returns a fully configured FastAPI instance.
    """
    setup_logging("DEBUG" if settings.DEBUG else "INFO")

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Automated Video Generation System — "
            "InVideo-style AI-powered vertical video creator."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        print("VALIDATION ERROR:", exc.errors())

        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors()},
        )

    


    # ── Middleware ────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],       # Tighten in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_logger(request: Request, call_next):
        """Log every request with timing."""
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        logger.info(
            f"{request.method} {request.url.path} "
            f"→ {response.status_code} ({elapsed * 1000:.1f}ms)"
        )
        return response

    # ── Exception handlers ────────────────────────────────────────────────────

    @app.exception_handler(JobNotFoundError)
    async def job_not_found_handler(request: Request, exc: JobNotFoundError):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "not_found", "message": exc.message},
        )

    @app.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "validation_error", "message": exc.message},
        )

    @app.exception_handler(StorageError)
    async def storage_error_handler(request: Request, exc: StorageError):
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "storage_error", "message": exc.message},
        )

    @app.exception_handler(TTSProviderError)
    async def tts_error_handler(request: Request, exc: TTSProviderError):
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": "tts_error", "message": exc.message},
        )

    @app.exception_handler(VideoCompositionError)
    async def composition_error_handler(request: Request, exc: VideoCompositionError):
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "composition_error", "message": exc.message},
        )

    @app.exception_handler(VideoGenBaseError)
    async def base_error_handler(request: Request, exc: VideoGenBaseError):
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "internal_error", "message": exc.message},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {traceback.format_exc()}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_error",
                "message": "An unexpected error occurred.",
            },
        )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(video_router)
    app.include_router(health_router)
    app.include_router(auth_router)

    # ── Startup / shutdown events ─────────────────────────────────────────────
    @app.on_event("startup")
    async def on_startup():
        logger.info(
            f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} starting up..."
        )
        logger.info(f"   TTS provider  : {settings.TTS_PROVIDER}")
        logger.info(f"   Uploads dir   : {settings.UPLOADS_DIR}")
        logger.info(f"   Outputs dir   : {settings.OUTPUTS_DIR}")
        logger.info(f"   Video size    : {settings.VIDEO_WIDTH}×{settings.VIDEO_HEIGHT}")

    @app.on_event("shutdown")
    async def on_shutdown():
        logger.info("👋 Shutting down gracefully...")
        # Shutdown background worker if Celery wasn't used
        try:
            from workers.background_worker import get_background_worker
            get_background_worker().shutdown(wait=False)
        except Exception:
            pass

    return app
