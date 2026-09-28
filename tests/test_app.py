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


def test_legacy_sentence_review_job_stays_visible() -> None:
    job = Job.model_validate(
        {
            "id": "legacy-job",
            "filename": "meeting.mp4",
            "review_status": "ready",
            "review_items": [
                {
                    "id": "old-item",
                    "segment_index": 0,
                    "start_seconds": 0,
                    "end_seconds": 3,
                    "original_text": "这是旧版整句校对。",
                    "suggested_text": "这是旧版句子校对。",
                    "confidence": 0.5,
                    "reason": "旧格式",
                }
            ],
        }
    )

    assert job.review_status == "idle"
    assert job.review_items == []
    assert job.review_stage == "需重新运行词级校对"


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


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is not installed")
def test_enhanced_review_and_apply_correction(tmp_path: Path) -> None:
    sample = tmp_path / "sample.wav"
    write_sample_wav(sample)
    app = create_app(Settings(data_dir=tmp_path / "runtime", mock_ai=True))

    with TestClient(app) as client, sample.open("rb") as audio:
        created = client.post(
            "/api/jobs",
            files={"file": ("sample.wav", audio, "audio/wav")},
            data={"speed": "1.5", "trim_silence": "false"},
        ).json()
        job_id = created["id"]
        review_response = client.post(f"/api/jobs/{job_id}/review")
        assert review_response.status_code == 202
        reviewed = client.get(f"/api/jobs/{job_id}").json()
        assert reviewed["review_status"] == "ready"
        assert len(reviewed["review_items"]) == 1
        item = reviewed["review_items"][0]
        assert item["context_text"] == "主持人：今天确认 Meet Mine 第一版流程。"
        assert item["original_term"] == "Meet Mine"
        assert item["suggested_term"] == "MeetMind"
        assert item["start_seconds"] == 0.25
        assert item["end_seconds"] == 0.58
        assert client.get(f"/api/jobs/{job_id}/review/{item['id']}/audio").status_code == 200

        manual_matches = client.get(
            f"/api/jobs/{job_id}/review/search",
            params={"term": "第一版"},
        )
        assert manual_matches.status_code == 200
        match = manual_matches.json()[0]
        assert match["context_text"] == item["context_text"]
        assert match["original_term"] == "第一版"

        apply_response = client.post(
            f"/api/jobs/{job_id}/review/apply",
            json={
                "corrections": [
                    {"item_id": item["id"], "replacement": "MeetMind"}
                ],
                "manual_corrections": [
                    {
                        "segment_index": match["segment_index"],
                        "term_start": match["term_start"],
                        "original_term": match["original_term"],
                        "replacement": "首版",
                    }
                ],
            },
        )
        assert apply_response.status_code == 202
        corrected = client.get(f"/api/jobs/{job_id}").json()

    assert corrected["review_status"] == "completed"
    assert "MeetMind" in corrected["transcript"]
    assert "Meet Mine" not in corrected["transcript"]
    assert "首版流程" in corrected["transcript"]
    assert corrected["review_items"][0]["correction_term"] == "MeetMind"
    assert corrected["review_manual_corrections"][0]["replacement"] == "首版"
