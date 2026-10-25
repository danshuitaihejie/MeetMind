from __future__ import annotations

import json
import shutil
import wave
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai import AIConfigurationError, AIService, MiniMaxAPIError
from app.config import Settings
from app.main import create_app
from app.models import AIUsageCall


def compatible_settings() -> Settings:
    return Settings(
        asr_api_key="asr-test-key",
        asr_base_url="https://speech.example.test/v1",
        text_api_key="text-test-key",
        text_base_url="https://chat.example.test/v1",
        transcription_model="word-timed-asr",
        summary_model="chat-model",
    )


def test_separate_compatible_speech_and_text_apis(tmp_path: Path) -> None:
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"demo-audio")
    calls: list[AIUsageCall] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "speech.example.test":
            assert request.url.path == "/v1/audio/transcriptions"
            assert request.headers["authorization"] == "Bearer asr-test-key"
            body = request.read()
            assert b"word-timed-asr" in body
            assert b"demo-audio" in body
            if b"verbose_json" in body:
                assert b"timestamp_granularities%5B%5D" not in body
                assert b'timestamp_granularities[]' in body
                return httpx.Response(200, json={
                    "text": "Pitch Me",
                    "usage": {"type": "duration", "seconds": 4},
                    "words": [
                        {"word": "Pitch", "start": 0.1, "end": 0.5},
                        {"word": "Me", "start": 0.5, "end": 0.8},
                    ],
                })
            assert b"Project Pitch Me" in body
            return httpx.Response(200, json={"text": "Pitch Me"})
        assert request.url.host == "chat.example.test"
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer text-test-key"
        payload = json.loads(request.read())
        assert payload["model"] == "chat-model"
        assert payload["max_tokens"] == 4096
        assert "thinking" not in payload
        assert "temperature" not in payload
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "# Minutes\n\nDecision: proceed."}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
        })

    service = AIService(
        compatible_settings(), transport=httpx.MockTransport(handler),
        usage_recorder=calls.append,
    )
    assert service.transcribe(audio, "Project Pitch Me") == "Pitch Me"
    segments = service.transcribe_detailed(audio)
    assert [(token.text, token.start_seconds, token.end_seconds)
            for token in segments[0].tokens] == [
                ("Pitch", 0.1, 0.5), ("Me", 0.5, 0.8),
            ]
    assert service.summarize("Pitch Me") == "# Minutes\n\nDecision: proceed."
    assert calls[1].audio_duration_seconds == 4
    assert calls[2].total_tokens == 28


def test_review_requires_actual_word_timestamps(tmp_path: Path) -> None:
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"demo-audio")
    service = AIService(
        compatible_settings(),
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200, json={"text": "Pitch Me", "segments": [
                {"text": "Pitch Me", "start": 0, "end": 1},
            ]},
        )),
    )
    with pytest.raises(MiniMaxAPIError, match="词级时间戳"):
        service.transcribe_detailed(audio)


def test_custom_key_needs_custom_url_and_health_is_provider_neutral(tmp_path: Path) -> None:
    incomplete = Settings(minimax_api_key="old-key", asr_api_key="different-key")
    assert not incomplete.ai_configured
    assert incomplete.resolved_asr_base_url is None
    missing_key = Settings(
        minimax_api_key="old-key", asr_base_url="https://speech.example.test/v1",
    )
    assert not missing_key.ai_configured
    assert missing_key.resolved_asr_key is None
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"demo-audio")
    with pytest.raises(AIConfigurationError, match="地址和密钥"):
        AIService(incomplete).transcribe(audio)

    settings = compatible_settings()
    settings.data_dir = tmp_path
    assert settings.ai_configured
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/health").json()
    assert health["ai_configured"] is True
    assert health["ai_provider"] == "语音 / 文本 API"


def test_compatible_text_can_use_max_completion_tokens() -> None:
    settings = compatible_settings()
    settings.text_max_tokens_field = "max_completion_tokens"

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        assert payload["max_completion_tokens"] == 4096
        assert "max_tokens" not in payload
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "# 会议纪要"}}],
        })

    service = AIService(settings, transport=httpx.MockTransport(handler))
    assert service.summarize("会议内容") == "# 会议纪要"


def test_environment_can_mix_default_speech_with_compatible_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "MEETMIND_ASR_API_KEY", "MEETMIND_ASR_BASE_URL", "MEETMIND_ASR_API_FORMAT",
        "MEETMIND_TEXT_API_FORMAT", "MEETMIND_MINIMAX_BASE_URL",
        "MEETMIND_TEXT_MAX_TOKENS_FIELD",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MINIMAX_API_KEY", "default-key")
    monkeypatch.setenv("MEETMIND_TEXT_API_KEY", "other-key")
    monkeypatch.setenv("MEETMIND_TEXT_BASE_URL", "https://chat.example.test/v1")
    monkeypatch.setenv("MEETMIND_SUMMARY_MODEL", "other-chat-model")
    settings = Settings.from_env()

    assert settings.ai_configured
    assert settings.resolved_asr_format == "minimax"
    assert settings.resolved_text_format == "openai"
    assert settings.resolved_asr_key == "default-key"
    assert settings.resolved_text_key == "other-key"
    assert settings.resolved_asr_base_url == "https://api.minimaxi.com"
    assert settings.resolved_text_base_url == "https://chat.example.test/v1"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is not installed")
def test_compatible_provider_can_process_meeting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "meeting.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 16000)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "speech.example.test":
            assert request.url.path == "/v1/audio/transcriptions"
            return httpx.Response(200, json={"text": "决定下周演示。"})
        assert request.url.host == "chat.example.test"
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "# 会议纪要\n\n决定下周演示。"}}],
        })

    monkeypatch.setattr(
        "app.main.AIService",
        lambda settings: AIService(settings, transport=httpx.MockTransport(handler)),
    )
    settings = compatible_settings()
    settings.data_dir = tmp_path / "runtime"
    with TestClient(create_app(settings)) as client, source.open("rb") as upload:
        response = client.post(
            "/api/jobs", files={"file": ("meeting.wav", upload, "audio/wav")},
            data={"speed": "1", "trim_silence": "false"},
        )
        assert response.status_code == 202
        job = client.get(f"/api/jobs/{response.json()['id']}").json()
    assert job["status"] == "completed"
    assert job["transcript"] == "决定下周演示。"
    assert job["minutes"].startswith("# 会议纪要")
