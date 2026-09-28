from __future__ import annotations

import shutil
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import Job, JobStatus


def write_sample_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 16000)


def test_health_reports_configuration(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, mock_ai=True))
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ai_configured"] is True


def test_rejects_unsupported_upload(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, mock_ai=True))
    with TestClient(app) as client:
        response = client.post(
            "/api/jobs",
            files={"file": ("notes.txt", b"hello", "text/plain")},
            data={"speed": "1.5", "trim_silence": "true"},
        )
    assert response.status_code == 415


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is not installed")
def test_end_to_end_mock_pipeline(tmp_path: Path) -> None:
    sample = tmp_path / "sample.wav"
    write_sample_wav(sample)
    app = create_app(Settings(data_dir=tmp_path / "runtime", mock_ai=True))

    with TestClient(app) as client, sample.open("rb") as audio:
        response = client.post(
            "/api/jobs",
            files={"file": ("sample.wav", audio, "audio/wav")},
            data={"speed": "1.5", "trim_silence": "false", "context": "MeetMind 评审"},
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        job = client.get(f"/api/jobs/{job_id}").json()
        assert job["status"] == "completed"
        assert job["compressed_size_bytes"] > 0
        assert "MeetMind" in job["minutes"]
        assert client.get(f"/api/jobs/{job_id}/audio").status_code == 200


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is not installed")
def test_retry_failed_job_without_reupload(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    app = create_app(Settings(data_dir=runtime, mock_ai=True))
    store = app.state.store
    store.create(
        Job(
            id="failed-job",
            filename="meeting.wav",
            status=JobStatus.failed,
            stage="处理失败",
            error="temporary provider error",
            original_size_bytes=32000,
            trim_silence=False,
        )
    )
    source = store.job_dir("failed-job") / "source.wav"
    write_sample_wav(source)

    with TestClient(app) as client:
        response = client.post("/api/jobs/failed-job/retry")
        assert response.status_code == 202
        job = client.get("/api/jobs/failed-job").json()

    assert job["status"] == "completed"
    assert job["error"] is None
    assert "MeetMind" in job["minutes"]
