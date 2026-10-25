from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    data_dir: Path = Path("data")
    max_upload_mb: int = 2048
    transcription_model: str = "asr-1.0"
    summary_model: str = "MiniMax-M2.7"
    minimax_api_key: str | None = None
    minimax_base_url: str = "https://api.minimaxi.com"
    asr_api_key: str | None = None
    asr_base_url: str | None = None
    asr_api_format: str | None = None
    text_api_key: str | None = None
    text_base_url: str | None = None
    text_api_format: str | None = None
    text_max_tokens_field: str | None = None
    mock_ai: bool = False

    @property
    def resolved_asr_format(self) -> str:
        return self.asr_api_format or (
            "openai" if self.asr_api_key or self.asr_base_url else "minimax"
        )

    @property
    def resolved_text_format(self) -> str:
        return self.text_api_format or (
            "openai" if self.text_api_key or self.text_base_url else "minimax"
        )

    @property
    def resolved_asr_key(self) -> str | None:
        if self.asr_api_key:
            return self.asr_api_key
        if not self.asr_base_url and self.resolved_asr_format == "minimax":
            return self.minimax_api_key
        return None

    @property
    def resolved_text_key(self) -> str | None:
        if self.text_api_key:
            return self.text_api_key
        if not self.text_base_url and self.resolved_text_format == "minimax":
            return self.minimax_api_key
        return None

    @property
    def resolved_asr_base_url(self) -> str | None:
        if self.asr_base_url:
            return self.asr_base_url.rstrip("/")
        return self.minimax_base_url if not self.asr_api_key else None

    @property
    def resolved_text_base_url(self) -> str | None:
        if self.text_base_url:
            return self.text_base_url.rstrip("/")
        return self.minimax_base_url if not self.text_api_key else None

    @property
    def ai_configured(self) -> bool:
        return self.mock_ai or bool(
            self.resolved_asr_format in {"minimax", "openai"}
            and self.resolved_text_format in {"minimax", "openai"}
            and self.resolved_asr_key and self.resolved_text_key
            and self.resolved_asr_base_url and self.resolved_text_base_url
            and self.text_max_tokens_field in {None, "max_tokens", "max_completion_tokens"}
        )

    @property
    def ai_provider_label(self) -> str:
        return (
            "MiniMax" if self.resolved_asr_format == self.resolved_text_format == "minimax"
            and not self.asr_base_url and not self.text_base_url else "语音 / 文本 API"
        )

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            data_dir=Path(os.getenv("MEETMIND_DATA_DIR", "data")),
            max_upload_mb=int(os.getenv("MEETMIND_MAX_UPLOAD_MB", "2048")),
            transcription_model=os.getenv("MEETMIND_TRANSCRIPTION_MODEL", "asr-1.0"),
            summary_model=os.getenv("MEETMIND_SUMMARY_MODEL", "MiniMax-M2.7"),
            minimax_api_key=os.getenv("MINIMAX_API_KEY") or None,
            minimax_base_url=os.getenv(
                "MEETMIND_MINIMAX_BASE_URL", "https://api.minimaxi.com"
            ).rstrip("/"),
            asr_api_key=os.getenv("MEETMIND_ASR_API_KEY") or None,
            asr_base_url=os.getenv("MEETMIND_ASR_BASE_URL") or None,
            asr_api_format=os.getenv("MEETMIND_ASR_API_FORMAT") or None,
            text_api_key=os.getenv("MEETMIND_TEXT_API_KEY") or None,
            text_base_url=os.getenv("MEETMIND_TEXT_BASE_URL") or None,
            text_api_format=os.getenv("MEETMIND_TEXT_API_FORMAT") or None,
            text_max_tokens_field=os.getenv("MEETMIND_TEXT_MAX_TOKENS_FIELD") or None,
            mock_ai=_as_bool(os.getenv("MEETMIND_MOCK_AI")),
        )
