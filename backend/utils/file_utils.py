"""
utils/file_utils.py
--------------------
General-purpose file helpers used across agents and services.
All functions are pure and raise only VideoGenBaseError subclasses.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import List, Optional

from core.exceptions import StorageError
from core.logging import get_logger

logger = get_logger("FileUtils")


# ── Path helpers ──────────────────────────────────────────────────────────────

def ensure_dir(path: str | Path) -> Path:
    """Create a directory (and parents) if it doesn't exist. Returns Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_filename(name: str) -> str:
    """
    Sanitise a filename: replace spaces and special chars with underscores.
    Preserves the file extension.
    """
    stem = Path(name).stem
    suffix = Path(name).suffix
    clean = "".join(c if c.isalnum() or c in "-_." else "_" for c in stem)
    return f"{clean}{suffix}"


def list_files(directory: str | Path, extension: str = "") -> List[Path]:
    """
    Return all files in `directory` optionally filtered by extension.
    Returns an empty list if directory doesn't exist.
    """
    d = Path(directory)
    if not d.exists():
        return []
    pattern = f"*{extension}" if extension else "*"
    return sorted(d.glob(pattern))


# ── File info ─────────────────────────────────────────────────────────────────

def file_size_mb(path: str | Path) -> float:
    """Return file size in megabytes."""
    try:
        return Path(path).stat().st_size / (1024 * 1024)
    except OSError:
        return 0.0


def file_checksum(path: str | Path, algorithm: str = "md5") -> str:
    """
    Compute a checksum of a file for integrity checking.
    Returns hex digest string.
    """
    h = hashlib.new(algorithm)
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError as exc:
        raise StorageError(f"Cannot compute checksum of {path}: {exc}") from exc


# ── Copy / move ───────────────────────────────────────────────────────────────

def copy_file(src: str | Path, dest: str | Path) -> Path:
    """
    Copy src → dest. Creates dest's parent directory if needed.
    Returns the destination Path.
    """
    src_path = Path(src)
    dest_path = Path(dest)

    if not src_path.exists():
        raise StorageError(f"Source file does not exist: {src}")

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, dest_path)
    logger.debug(f"Copied {src_path.name} → {dest_path}")
    return dest_path


def move_file(src: str | Path, dest: str | Path) -> Path:
    """Move src → dest. Returns the destination Path."""
    src_path = Path(src)
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src_path), dest_path)
    return dest_path


# ── Temp file naming ──────────────────────────────────────────────────────────

def temp_path(base_dir: str | Path, prefix: str, suffix: str) -> str:
    """
    Generate a unique temp file path inside base_dir.
    Does NOT create the file — just returns the path string.

    Example: temp_path("/tmp/job1", "clip", ".mp4")
    → "/tmp/job1/clip_a3f7c2.mp4"
    """
    import uuid
    short_id = str(uuid.uuid4()).replace("-", "")[:8]
    filename = f"{prefix}_{short_id}{suffix}"
    return str(Path(base_dir) / filename)


# ── Video-specific helpers ────────────────────────────────────────────────────

def is_video_file(path: str | Path) -> bool:
    """Return True if the file has a recognised video extension."""
    VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
    return Path(path).suffix.lower() in VIDEO_EXTS


def get_video_files(directory: str | Path) -> List[Path]:
    """Return all video files in a directory."""
    d = Path(directory)
    if not d.exists():
        return []
    return [
        f for f in sorted(d.iterdir())
        if f.is_file() and is_video_file(f)
    ]
