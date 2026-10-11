"""
tests/test_file_utils.py
-------------------------
Unit tests for utils/file_utils.py — pure file-system helpers.
Uses pytest's tmp_path fixture; no real data is touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utils.file_utils import (
    copy_file,
    ensure_dir,
    file_checksum,
    file_size_mb,
    get_video_files,
    is_video_file,
    list_files,
    move_file,
    safe_filename,
    temp_path,
)
from core.exceptions import StorageError


# ── ensure_dir ────────────────────────────────────────────────────────────────

def test_ensure_dir_creates_nested(tmp_path):
    target = tmp_path / "a" / "b" / "c"
    assert not target.exists()
    result = ensure_dir(target)
    assert result.exists()
    assert result.is_dir()


def test_ensure_dir_existing_is_idempotent(tmp_path):
    ensure_dir(tmp_path)   # Already exists — should not raise
    assert tmp_path.exists()


# ── safe_filename ─────────────────────────────────────────────────────────────

def test_safe_filename_spaces_become_underscores():
    assert safe_filename("my clip file.mp4") == "my_clip_file.mp4"


def test_safe_filename_preserves_extension():
    result = safe_filename("clip@2024!.MOV")
    assert result.endswith(".MOV")


def test_safe_filename_no_special_chars():
    result = safe_filename("hello world (2).mp4")
    assert "(" not in result
    assert ")" not in result
    assert " " not in result


# ── list_files ────────────────────────────────────────────────────────────────

def test_list_files_all(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.mp4").write_bytes(b"\x00")
    files = list_files(tmp_path)
    assert len(files) == 2


def test_list_files_filtered_by_extension(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.mp4").write_bytes(b"\x00")
    (tmp_path / "c.mp4").write_bytes(b"\x00")
    mp4s = list_files(tmp_path, ".mp4")
    assert len(mp4s) == 2
    assert all(f.suffix == ".mp4" for f in mp4s)


def test_list_files_nonexistent_dir_returns_empty():
    files = list_files("/this/path/does/not/exist")
    assert files == []


# ── file_size_mb ──────────────────────────────────────────────────────────────

def test_file_size_mb_returns_correct_size(tmp_path):
    f = tmp_path / "data.bin"
    f.write_bytes(b"\x00" * 1024 * 1024)   # 1 MB
    assert abs(file_size_mb(f) - 1.0) < 0.01


def test_file_size_mb_missing_file_returns_zero():
    assert file_size_mb("/nonexistent/file.mp4") == 0.0


# ── file_checksum ─────────────────────────────────────────────────────────────

def test_file_checksum_consistent(tmp_path):
    f = tmp_path / "test.bin"
    f.write_bytes(b"hello world")
    cs1 = file_checksum(f)
    cs2 = file_checksum(f)
    assert cs1 == cs2


def test_file_checksum_different_contents_differ(tmp_path):
    f1 = tmp_path / "a.bin"
    f2 = tmp_path / "b.bin"
    f1.write_bytes(b"aaa")
    f2.write_bytes(b"bbb")
    assert file_checksum(f1) != file_checksum(f2)


def test_file_checksum_missing_raises(tmp_path):
    with pytest.raises(StorageError):
        file_checksum(tmp_path / "missing.bin")


# ── copy_file ─────────────────────────────────────────────────────────────────

def test_copy_file_creates_dest(tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"\x00" * 100)
    dest = tmp_path / "subdir" / "dest.mp4"

    copy_file(src, dest)

    assert dest.exists()
    assert dest.read_bytes() == src.read_bytes()


def test_copy_file_missing_src_raises(tmp_path):
    with pytest.raises(StorageError, match="does not exist"):
        copy_file(tmp_path / "ghost.mp4", tmp_path / "dest.mp4")


# ── move_file ─────────────────────────────────────────────────────────────────

def test_move_file_src_no_longer_exists(tmp_path):
    src = tmp_path / "to_move.mp4"
    src.write_bytes(b"\x01" * 50)
    dest = tmp_path / "moved.mp4"

    move_file(src, dest)

    assert dest.exists()
    assert not src.exists()


# ── temp_path ─────────────────────────────────────────────────────────────────

def test_temp_path_unique(tmp_path):
    p1 = temp_path(tmp_path, "clip", ".mp4")
    p2 = temp_path(tmp_path, "clip", ".mp4")
    assert p1 != p2


def test_temp_path_correct_extension(tmp_path):
    p = temp_path(tmp_path, "audio", ".mp3")
    assert p.endswith(".mp3")


def test_temp_path_inside_base_dir(tmp_path):
    p = temp_path(tmp_path, "clip", ".mp4")
    assert str(tmp_path) in p


# ── is_video_file ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("filename,expected", [
    ("clip.mp4", True),
    ("video.MOV", True),
    ("movie.avi", True),
    ("file.mkv", True),
    ("clip.webm", True),
    ("script.txt", False),
    ("image.jpg", False),
    ("audio.mp3", False),
    ("noextension", False),
])
def test_is_video_file(filename, expected):
    assert is_video_file(filename) == expected


# ── get_video_files ───────────────────────────────────────────────────────────

def test_get_video_files_returns_only_videos(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"\x00")
    (tmp_path / "b.mp4").write_bytes(b"\x00")
    (tmp_path / "c.txt").write_text("text")
    (tmp_path / "d.jpg").write_bytes(b"\xff")

    videos = get_video_files(tmp_path)
    assert len(videos) == 2
    assert all(v.suffix == ".mp4" for v in videos)


def test_get_video_files_empty_dir(tmp_path):
    videos = get_video_files(tmp_path)
    assert videos == []
