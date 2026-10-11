"""
services/auth_service.py
------------------------
Minimal, dependency-free accounts (stdlib only):
  - users stored as JSON files in data/users/
  - passwords: PBKDF2-HMAC-SHA256, per-user random salt
  - tokens: HMAC-signed "payload.signature" with an expiry (not JWT, but equivalent)
Only used when settings.AUTH_ENABLED is true.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from pathlib import Path
from typing import Optional

from core.config import settings
from core.exceptions import ValidationError

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ITERATIONS = 200_000


class AuthError(Exception):
    pass


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class AuthService:
    def __init__(self) -> None:
        self.dir: Path = settings.DATA_DIR / "users"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._secret = self._load_secret()

    @classmethod
    def create(cls) -> "AuthService":
        return cls()

    # ── Accounts ──────────────────────────────────────────────────────────────

    def register(self, email: str, password: str) -> dict:
        email = email.strip().lower()
        if not _EMAIL_RE.match(email) or len(email) > 254:
            raise ValidationError("Enter a valid email address.")
        if len(password) < 8:
            raise ValidationError("Password must be at least 8 characters.")
        path = self._user_path(email)
        if path.exists():
            raise ValidationError("An account with this email already exists.")
        salt = secrets.token_bytes(16)
        user = {
            "id": str(uuid.uuid4()),
            "email": email,
            "salt": _b64(salt),
            "hash": _b64(self._hash(password, salt)),
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(user), encoding="utf-8")
        tmp.replace(path)
        return user

    def login(self, email: str, password: str) -> dict:
        user = self._read(email.strip().lower())
        # Always hash, even for unknown users, so timing doesn't reveal which emails exist.
        salt = _unb64(user["salt"]) if user else b"\0" * 16
        candidate = _b64(self._hash(password, salt))
        if not user or not hmac.compare_digest(candidate, user["hash"]):
            raise AuthError("Incorrect email or password.")
        return user

    def get_by_id(self, uid: str) -> Optional[dict]:
        for f in self.dir.glob("*.json"):
            try:
                u = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if u.get("id") == uid:
                return u
        return None

    # ── Tokens ────────────────────────────────────────────────────────────────

    def issue_token(self, user: dict) -> str:
        payload = _b64(json.dumps({"uid": user["id"], "exp": int(time.time()) + settings.AUTH_TOKEN_TTL_HOURS * 3600}).encode())
        return f"{payload}.{self._sign(payload)}"

    def verify_token(self, token: str) -> Optional[str]:
        try:
            payload, sig = token.split(".", 1)
            if not hmac.compare_digest(sig, self._sign(payload)):
                return None
            data = json.loads(_unb64(payload))
            return data["uid"] if data["exp"] > time.time() else None
        except Exception:
            return None

    # ── Internals ─────────────────────────────────────────────────────────────

    def _sign(self, payload: str) -> str:
        return _b64(hmac.new(self._secret, payload.encode(), hashlib.sha256).digest())

    @staticmethod
    def _hash(password: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)

    def _user_path(self, email: str) -> Path:
        return self.dir / (hashlib.sha256(email.encode()).hexdigest()[:32] + ".json")

    def _read(self, email: str) -> Optional[dict]:
        p = self._user_path(email)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    @staticmethod
    def _load_secret() -> bytes:
        if settings.AUTH_SECRET:
            return settings.AUTH_SECRET.encode()
        f = settings.DATA_DIR / ".auth_secret"
        if not f.exists():
            settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
            f.write_text(secrets.token_hex(32), encoding="utf-8")
        return f.read_text(encoding="utf-8").strip().encode()
