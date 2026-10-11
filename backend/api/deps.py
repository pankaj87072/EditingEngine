"""api/deps.py: shared FastAPI dependencies."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Request, status

from core.config import settings
from services.auth_service import AuthService

_auth: Optional[AuthService] = None


def auth_service() -> AuthService:
    global _auth
    if _auth is None:
        _auth = AuthService.create()
    return _auth


def current_user(request: Request) -> Optional[str]:
    """
    Returns the user id, or None when auth is disabled (single-user mode).
    Accepts `Authorization: Bearer <token>` or `?token=` (needed because
    <video src> and download links cannot send headers).
    """
    if not settings.AUTH_ENABLED:
        return None
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("token", "")
    uid = auth_service().verify_token(token) if token else None
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in to continue.")
    return uid
