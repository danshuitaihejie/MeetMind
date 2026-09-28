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
    mock_ai: bool = False

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
            mock_ai=_as_bool(os.getenv("MEETMIND_MOCK_AI")),
        )
