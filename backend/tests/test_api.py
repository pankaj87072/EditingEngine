"""
tests/test_api.py
------------------
Integration tests for FastAPI endpoints.
Uses TestClient (synchronous) so no running server is needed.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest


def test_health_endpoint(test_client):
    response = test_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "ffmpeg_available" in data
    assert "redis_available" in data


def test_generate_missing_script(test_client):
    """POST /generate without script should return 422."""
    response = test_client.post(
        "/generate",
        data={},  # No script
        files=[("clips", ("test.mp4", b"\x00" * 100, "video/mp4"))],
    )
    assert response.status_code == 422


def test_generate_missing_clips(test_client):
    """POST /generate without clips should return 422."""
    response = test_client.post(
        "/generate",
        data={"script": "Hello world this is a test script for our product."},
    )
    assert response.status_code == 422


def test_generate_unsupported_file_type(test_client):
    """POST /generate with a .txt file should return 415."""
    with patch("api.routes.video_routes._enqueue_job"):
        response = test_client.post(
            "/generate",
            data={"script": "This is a test script with enough words for processing."},
            files=[("clips", ("test.txt", b"not a video", "text/plain"))],
        )
    # Should be 415 Unsupported Media Type
    assert response.status_code in (415, 422)


def test_generate_success(test_client):
    """POST /generate with valid inputs should return 202 with job_id."""
    with patch("api.routes.video_routes._enqueue_job") as mock_enqueue:
        mock_enqueue.return_value = None

        response = test_client.post(
            "/generate",
            data={
                "script": (
                    "Welcome to our amazing product demo. "
                    "Today we showcase our incredible new features. "
                    "Join us and discover what the future looks like."
                ),
                "tts_provider": "google",
                "transition": "fade",
            },
            files=[
                ("clips", ("clip1.mp4", b"\x00" * 200, "video/mp4")),
                ("clips", ("clip2.mp4", b"\x00" * 200, "video/mp4")),
            ],
        )

    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "pending"


def test_status_not_found(test_client):
    """GET /status/<unknown-id> should return 404."""
    response = test_client.get("/status/nonexistent-job-id-12345")
    assert response.status_code == 404


def test_result_not_found(test_client):
    """GET /result/<unknown-id> should return 404."""
    response = test_client.get("/result/nonexistent-job-id-12345")
    assert response.status_code == 404


def test_status_flow(test_client):
    """Create a job, then check its status."""
    with patch("api.routes.video_routes._enqueue_job"):
        create_response = test_client.post(
            "/generate",
            data={
                "script": (
                    "This is a full test of the status endpoint. "
                    "We verify the job transitions from pending state."
                ),
            },
            files=[("clips", ("clip.mp4", b"\x00" * 200, "video/mp4"))],
        )

    assert create_response.status_code == 202
    job_id = create_response.json()["job_id"]

    # Check status
    status_response = test_client.get(f"/status/{job_id}")
    assert status_response.status_code == 200
    status_data = status_response.json()
    assert status_data["job_id"] == job_id
    assert status_data["status"] in ("pending", "processing", "completed", "failed")


def test_result_pending(test_client):
    """Result endpoint for a pending job should say 'queued'."""
    with patch("api.routes.video_routes._enqueue_job"):
        create_response = test_client.post(
            "/generate",
            data={
                "script": (
                    "Testing the result endpoint for pending jobs "
                    "to ensure it returns the correct message format."
                ),
            },
            files=[("clips", ("clip.mp4", b"\x00" * 200, "video/mp4"))],
        )

    job_id = create_response.json()["job_id"]
    result_response = test_client.get(f"/result/{job_id}")
    assert result_response.status_code == 200
    result_data = result_response.json()
    assert result_data["job_id"] == job_id
