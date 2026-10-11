"""api/routes/auth_routes.py: optional accounts (active only when AUTH_ENABLED=true)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.deps import auth_service, current_user
from core.config import settings
from core.exceptions import ValidationError
from services.auth_service import AuthError

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    email: str
    password: str


def _require_enabled() -> None:
    if not settings.AUTH_ENABLED:
        raise HTTPException(status_code=404, detail="Accounts are not enabled on this server.")


@router.get("/config", summary="Does this server require sign-in?")
async def auth_config():
    return {"enabled": settings.AUTH_ENABLED}


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: Credentials):
    _require_enabled()
    try:
        user = auth_service().register(body.email, body.password)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message)
    return {"token": auth_service().issue_token(user), "email": user["email"]}


@router.post("/login")
async def login(body: Credentials):
    _require_enabled()
    try:
        user = auth_service().login(body.email, body.password)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return {"token": auth_service().issue_token(user), "email": user["email"]}


@router.get("/me")
async def me(uid: Optional[str] = Depends(current_user)):
    _require_enabled()
    user = auth_service().get_by_id(uid) if uid else None
    if not user:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    return {"email": user["email"]}
