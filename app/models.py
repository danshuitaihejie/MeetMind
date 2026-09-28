from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class Job(BaseModel):
    id: str
    filename: str
    content_type: str | None = None
    status: JobStatus = JobStatus.queued
    stage: str = "等待处理"
    progress: int = Field(default=0, ge=0, le=100)
    speed: float = 1.5
    trim_silence: bool = True
    context: str = ""
    original_duration_seconds: float | None = None
    compressed_duration_seconds: float | None = None
    original_size_bytes: int = 0
    compressed_size_bytes: int | None = None
    transcript: str | None = None
    minutes: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def compression_ratio(self) -> float | None:
        if not self.original_duration_seconds or self.compressed_duration_seconds is None:
            return None
        return self.compressed_duration_seconds / self.original_duration_seconds


class HealthResponse(BaseModel):
    ok: bool
    ffmpeg_available: bool
    ai_configured: bool
    ai_provider: str = "MiniMax"
    transcription_model: str
    summary_model: str
