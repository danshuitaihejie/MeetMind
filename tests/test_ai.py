from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.ai import AIService, MiniMaxAPIError
from app.config import Settings


def make_service(handler: httpx.MockTransport) -> AIService:
    return AIService(
        Settings(minimax_api_key="test-key", minimax_base_url="https://api.example.test"),
        transport=handler,
        sleeper=lambda _: None,
    )


def test_minimax_transcription_request(tmp_path: Path) -> None:
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"fake-mp3")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/speech_to_text"
        assert request.headers["authorization"] == "Bearer test-key"
        body = request.read()
        assert b'asr-1.0' in body
        assert b'filename="meeting.mp3"' in body
        return httpx.Response(200, json={"text": " 这是会议转写。 ", "duration": 12.5})

    service = make_service(httpx.MockTransport(handler))
    assert service.transcribe(audio) == "这是会议转写。"


def test_minimax_summary_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.read())
        assert payload["model"] == "MiniMax-M2.7"
        assert payload["messages"][0]["role"] == "system"
        assert "会议原文" in payload["messages"][1]["content"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "# 会议纪要\n\n完成。"}}]},
        )

    service = make_service(httpx.MockTransport(handler))
    assert service.summarize("会议原文") == "# 会议纪要\n\n完成。"


def test_minimax_api_error_is_readable(tmp_path: Path) -> None:
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"fake-mp3")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid api key"})

    service = make_service(httpx.MockTransport(handler))
    with pytest.raises(MiniMaxAPIError, match="401"):
        service.transcribe(audio)


def test_minimax_retries_temporary_asr_failure_with_full_file(tmp_path: Path) -> None:
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"full-audio-payload")
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        body = request.read()
        assert b"full-audio-payload" in body
        if attempts < 3:
            return httpx.Response(
                500,
                json={
                    "type": "error",
                    "error": {"message": "system error, speech recognition failed (1033)"},
                },
            )
        return httpx.Response(200, json={"text": "重试成功", "duration": 10})

    service = make_service(httpx.MockTransport(handler))
    assert service.transcribe(audio) == "重试成功"
    assert attempts == 3
