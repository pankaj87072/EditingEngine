"""
tests/test_job_management.py
-----------------------------
Covers the endpoints/fields added for the web frontend:
  - style form fields on POST /generate
  - GET /result/{id}/stream (Range support)
  - DELETE /jobs/{id}
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from api.routes import video_routes
from core.config import settings
from models.schema import Job, JobStatus

PAYLOAD = bytes(range(256)) * 40  # 10,240 bytes


@pytest.fixture
def completed_job():
    job_id = str(uuid.uuid4())
    job = Job(job_id=job_id, script="x")
    video_routes._job_service.create_job(job)
    out = settings.OUTPUTS_DIR / job_id / f"{job_id}_final.mp4"
    out.write_bytes(PAYLOAD)
    video_routes._job_service.mark_completed(job_id, str(out), f"/result/{job_id}/download")
    yield job_id
    try:
        video_routes._job_service.delete_job(job_id)
    except Exception:
        pass


def test_generate_accepts_style_fields(test_client):
    with patch("api.routes.video_routes._enqueue_job"):
        r = test_client.post(
            "/generate",
            data={
                "script": "A script with a handful of words in it.",
                "intensity": "dynamic",
                "caption_style": "bold",
                "subtitle_position": "center",
            },
            files=[("clips", ("a.mp4", b"\x00" * 64, "video/mp4"))],
        )
    assert r.status_code == 202
    job = video_routes._job_service.get_job(r.json()["job_id"])
    assert (job.intensity.value, job.caption_style.value, job.subtitle_position.value) == ("dynamic", "bold", "center")
    video_routes._job_service.delete_job(job.job_id)


def test_generate_rejects_bad_style_value(test_client):
    with patch("api.routes.video_routes._enqueue_job"):
        r = test_client.post(
            "/generate",
            data={"script": "A script with a handful of words in it.", "intensity": "extreme"},
            files=[("clips", ("a.mp4", b"\x00" * 64, "video/mp4"))],
        )
    assert r.status_code == 422


def test_generate_strips_path_from_filename(test_client):
    with patch("api.routes.video_routes._enqueue_job"):
        r = test_client.post(
            "/generate",
            data={"script": "A script with a handful of words in it."},
            files=[("clips", ("../../evil.mp4", b"\x00" * 64, "video/mp4"))],
        )
    assert r.status_code == 202
    job = video_routes._job_service.get_job(r.json()["job_id"])
    assert job.clip_paths[0].endswith(f"{job.job_id}/evil.mp4")
    video_routes._job_service.delete_job(job.job_id)


def test_stream_full_file(test_client, completed_job):
    r = test_client.get(f"/result/{completed_job}/stream")
    assert r.status_code == 200
    assert r.headers["accept-ranges"] == "bytes"
    assert r.content == PAYLOAD


@pytest.mark.parametrize(
    "header,expected",
    [("bytes=0-99", PAYLOAD[:100]), ("bytes=10000-", PAYLOAD[10000:]), ("bytes=-50", PAYLOAD[-50:])],
)
def test_stream_range(test_client, completed_job, header, expected):
    r = test_client.get(f"/result/{completed_job}/stream", headers={"Range": header})
    assert r.status_code == 206
    assert r.content == expected
    assert r.headers["content-range"].endswith(f"/{len(PAYLOAD)}")


def test_stream_unsatisfiable_range(test_client, completed_job):
    r = test_client.get(f"/result/{completed_job}/stream", headers={"Range": "bytes=99999-"})
    assert r.status_code == 416


def test_stream_not_ready(test_client):
    job = Job(job_id=str(uuid.uuid4()), script="x")
    video_routes._job_service.create_job(job)
    assert test_client.get(f"/result/{job.job_id}/stream").status_code == 409
    video_routes._job_service.delete_job(job.job_id)


def test_delete_completed_job(test_client, completed_job):
    assert test_client.delete(f"/jobs/{completed_job}").status_code == 204
    assert test_client.get(f"/status/{completed_job}").status_code == 404
    assert test_client.delete(f"/jobs/{completed_job}").status_code == 404


def test_delete_blocks_active_job_but_allows_stale(test_client):
    job = Job(job_id=str(uuid.uuid4()), script="x", status=JobStatus.PROCESSING)
    video_routes._job_service.create_job(job)
    assert test_client.delete(f"/jobs/{job.job_id}").status_code == 409

    stale = video_routes._job_service.get_job(job.job_id)
    stale.updated_at = datetime.utcnow() - timedelta(hours=2)
    video_routes._job_service._write(stale)  # bypass touch()
    assert test_client.delete(f"/jobs/{job.job_id}").status_code == 204


def test_delete_rejects_non_uuid(test_client):
    assert test_client.delete("/jobs/not-a-job").status_code == 404
