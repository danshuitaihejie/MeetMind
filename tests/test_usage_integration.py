from __future__ import annotations

import json
import shutil
import wave
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai import AIService
from app.config import Settings
from app.main import create_app
from app.store import JobStore


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is not installed")
def test_usage_accumulates_across_retry_review_and_regeneration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = tmp_path / "sample.wav"
    with wave.open(str(sample), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 16000)
    text_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal text_calls
        if request.url.path == "/v1/speech_to_text":
            return httpx.Response(200, json={
                "text": "确认 Meet Mine 项目。", "duration": 1.0,
                "segments": [
                    {"start": 0, "end": 0.5, "text": "确认 Meet Mine 项目。", "speaker": "1"},
                ],
            })
        text_calls += 1
        if text_calls == 1:
            return httpx.Response(400, json={
                "error": "failed summary", "usage": {
                    "prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10,
                },
            })
        body = json.loads(request.read())
        system = body["messages"][0]["content"]
        content = "# 会议纪要\n\n确认项目。"
        if "只返回 JSON" in system:
            content = json.dumps({"candidates": [{
                "segment_index": 0, "original_term": "Meet Mine",
                "suggested_term": "MeetMind", "confidence": 0.6, "reason": "专有名词",
            }]})
        return httpx.Response(200, json={
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
                "prompt_tokens_details": {"cached_tokens": 30},
            },
        })

    monkeypatch.setattr(
        "app.main.AIService",
        lambda settings: AIService(settings, transport=httpx.MockTransport(handler)),
    )
    data_dir = tmp_path / "runtime"
    app = create_app(Settings(data_dir=data_dir, minimax_api_key="test-key"))
    with TestClient(app) as client, sample.open("rb") as audio:
        created = client.post(
            "/api/jobs", files={"file": ("sample.wav", audio, "audio/wav")},
            data={"speed": "1", "trim_silence": "false", "language": "zh"},
        ).json()
        job_id = created["id"]
        failed = client.get(f"/api/jobs/{job_id}").json()
        assert failed["status"] == "failed"
        assert failed["usage_summary"]["total_tokens"] == 10
        assert client.post(f"/api/jobs/{job_id}/retry").status_code == 202
        assert client.post(f"/api/jobs/{job_id}/review").status_code == 202
        reviewed = client.get(f"/api/jobs/{job_id}").json()
        item = reviewed["review_items"][0]
        assert client.post(f"/api/jobs/{job_id}/review/apply", json={
            "corrections": [{"item_id": item["id"], "replacement": "MeetMind"}],
        }).status_code == 202
        completed = client.get(f"/api/jobs/{job_id}").json()

    assert completed["review_status"] == "completed"
    assert [call["operation"] for call in completed["usage_calls"]] == [
        "transcription", "summary", "transcription", "summary", "review_transcription",
        "review_detection", "review_refinement", "summary_regeneration",
    ]
    summary = completed["usage_summary"]
    assert summary["input_tokens"] == 410
    assert summary["output_tokens"] == 80
    assert summary["total_tokens"] == 490
    assert summary["cached_input_tokens"] == 120
    assert summary["asr_duration_seconds"] == 3.0
    assert summary["failed_call_count"] == 1
    assert JobStore(data_dir / "jobs").get(job_id).usage_summary.total_tokens == 490
