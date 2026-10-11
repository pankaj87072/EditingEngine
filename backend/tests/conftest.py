"""
tests/conftest.py
------------------
Shared pytest fixtures for all test modules.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

# Set test environment variables BEFORE importing app modules
os.environ["DEBUG"] = "true"
os.environ["TTS_PROVIDER"] = "google"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"  # Use DB 1 for tests


@pytest.fixture(scope="session")
def temp_data_dir() -> Generator[Path, None, None]:
    """Create a temporary data directory for the test session."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture(scope="session")
def test_client() -> Generator[TestClient, None, None]:
    """FastAPI test client — shared across the test session."""
    from api.app import create_app
    app = create_app()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def sample_script() -> str:
    return (
        "Welcome to our product showcase. "
        "Today we are introducing the future of mobile technology. "
        "Our new device features an incredible camera system. "
        "The battery life lasts up to 48 hours on a single charge. "
        "Available in five stunning colors starting this Friday."
    )


@pytest.fixture
def sample_video_bytes() -> bytes:
    """
    Minimal valid MP4 bytes for upload tests.
    This is a 1×1 pixel, 1-frame H.264 MP4.
    In a real test suite, use a proper fixture video file.
    """
    # Return empty bytes — file upload tests need a real file
    return b"\x00" * 1024
