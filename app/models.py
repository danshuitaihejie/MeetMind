from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ReviewStatus(StrEnum):
    idle = "idle"
    processing = "processing"
    ready = "ready"
    applying = "applying"
    completed = "completed"
    failed = "failed"


class TranscriptSegment(BaseModel):
    index: int = Field(ge=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    text: str
    speaker: str | None = None


class ReviewSuggestion(BaseModel):
    segment_index: int = Field(ge=0)
    suggested_text: str
    confidence: float = Field(ge=0, le=1)
    reason: str


class ReviewItem(BaseModel):
    id: str
    segment_index: int = Field(ge=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    speaker: str | None = None
    original_text: str
    suggested_text: str
    confidence: float = Field(ge=0, le=1)
    reason: str
    ocr_text: list[str] = Field(default_factory=list)
    frame_count: int = Field(default=0, ge=0)
    correction: str | None = None


class ReviewCorrection(BaseModel):
    item_id: str
    text: str = Field(min_length=1, max_length=5000)


class ReviewSubmission(BaseModel):
    corrections: list[ReviewCorrection] = Field(max_length=20)


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
    review_status: ReviewStatus = ReviewStatus.idle
    review_stage: str = ""
    review_progress: int = Field(default=0, ge=0, le=100)
    review_items: list[ReviewItem] = Field(default_factory=list)
    review_error: str | None = None
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
