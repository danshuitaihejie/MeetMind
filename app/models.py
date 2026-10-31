from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field, model_validator


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


class TranscriptToken(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    text: str
    speaker: str | None = None


class TranscriptSegment(BaseModel):
    index: int = Field(ge=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    text: str
    speaker: str | None = None
    tokens: list[TranscriptToken] = Field(default_factory=list)


class ReviewSuggestion(BaseModel):
    segment_index: int = Field(ge=0)
    original_term: str = Field(min_length=1, max_length=100)
    suggested_term: str = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0, le=1)
    reason: str


class ReviewItem(BaseModel):
    id: str
    segment_index: int = Field(ge=0)
    term_start: int | None = Field(default=None, ge=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    speaker: str | None = None
    context_text: str
    original_term: str
    suggested_term: str
    confidence: float = Field(ge=0, le=1)
    reason: str
    ocr_text: list[str] = Field(default_factory=list)
    frame_count: int = Field(default=0, ge=0)
    correction_term: str | None = None
    source: Literal["ai", "agent"] = "ai"
    requires_confirmation: bool = False


class ReviewCorrection(BaseModel):
    item_id: str
    replacement: str = Field(min_length=1, max_length=100)


class ManualReviewCorrection(BaseModel):
    segment_index: int = Field(ge=0)
    term_start: int = Field(ge=0)
    original_term: str = Field(min_length=1, max_length=100)
    replacement: str = Field(min_length=1, max_length=100)
    learn_globally: bool = True


class ManualReviewMatch(BaseModel):
    segment_index: int = Field(ge=0)
    term_start: int = Field(ge=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    context_text: str
    original_term: str


class ReviewSubmission(BaseModel):
    corrections: list[ReviewCorrection] = Field(max_length=200)
    manual_corrections: list[ManualReviewCorrection] = Field(
        default_factory=list,
        max_length=200,
    )


class MinutesTextCorrection(BaseModel):
    start: int = Field(ge=0)
    original: str = Field(min_length=1, max_length=500)
    replacement: str = Field(min_length=1, max_length=500)


class MinutesCorrectionSubmission(BaseModel):
    source_version: int = Field(ge=1)
    latest_version: int = Field(ge=1)
    corrections: list[MinutesTextCorrection] = Field(min_length=1, max_length=100)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    language: Literal["en", "zh"] = "en"
    job_id: str | None = None
    job_ids: list[str] | None = Field(default=None, max_length=100)
    history: list[ChatTurn] = Field(default_factory=list, max_length=10)


class ChatPassage(BaseModel):
    text: str
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)


class ChatLocateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class ChatSource(BaseModel):
    job_id: str
    filename: str
    created_at: datetime
    passages: list[ChatPassage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource]
    retrieved: bool = False


class ChatSessionCreate(BaseModel):
    scope_job_ids: list[str] = Field(min_length=1, max_length=100)


class ChatSessionQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    language: Literal["en", "zh"] = "en"


class ChatSessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class ChatSessionMessage(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    role: Literal["user", "assistant"]
    content: str
    sources: list[ChatSource] = Field(default_factory=list)
    retrieved: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatSession(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    title: str = "新对话"
    title_is_manual: bool = False
    title_generated_by_ai: bool = False
    scope_job_ids: list[str]
    messages: list[ChatSessionMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatPronunciation(BaseModel):
    ipa: str = Field(min_length=1, max_length=100)
    language: Literal["en-US", "en-GB"] = "en-US"


class ChatNoteCreate(BaseModel):
    phrase: str = Field(min_length=1, max_length=100)
    language: Literal["en", "zh"] = "en"
    source_excerpt: str = Field(min_length=1, max_length=500)
    scope_job_ids: list[str] = Field(min_length=1, max_length=500)
    message_id: str = Field(min_length=1, max_length=100)
    session_id: str | None = Field(default=None, min_length=1, max_length=100)
    selection_start: int = Field(ge=0)
    selection_end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_selection(self) -> ChatNoteCreate:
        phrase = self.phrase.strip()
        if self.selection_end - self.selection_start != len(phrase):
            raise ValueError("标注位置与词语长度不一致")
        if phrase not in self.source_excerpt:
            raise ValueError("原文摘录中未包含所选词语")
        return self


class ChatNoteQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    language: Literal["en", "zh"] = "en"


class ChatNoteExchange(BaseModel):
    question: str
    answer: str
    sources: list[ChatSource] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatNote(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    phrase: str
    source_excerpt: str
    scope_job_ids: list[str]
    message_id: str
    session_id: str | None = None
    selection_start: int
    selection_end: int
    exchanges: list[ChatNoteExchange] = Field(default_factory=list)
    sources: list[ChatSource] = Field(default_factory=list)
    pronunciation: ChatPronunciation | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AIUsageCall(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    operation: str
    kind: str
    model: str
    attempt: int = Field(default=1, ge=1)
    status: str = "success"
    http_status: int | None = None
    request_id: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    audio_duration_seconds: float | None = Field(default=None, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AIUsageSummary(BaseModel):
    call_count: int
    text_call_count: int
    asr_call_count: int
    mock_call_count: int
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cached_input_tokens: int | None
    missing_text_usage_calls: int
    asr_duration_seconds: float | None
    missing_asr_duration_calls: int
    failed_call_count: int


class MinutesVersion(BaseModel):
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: Literal["initial", "regenerated", "legacy", "manual"]


class Job(BaseModel):
    id: str
    filename: str
    language: Literal["en", "zh"] = "zh"
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
    minutes_versions: list[MinutesVersion] = Field(default_factory=list)
    error: str | None = None
    usage_calls: list[AIUsageCall] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.idle
    review_stage: str = ""
    review_progress: int = Field(default=0, ge=0, le=100)
    review_items: list[ReviewItem] = Field(default_factory=list)
    review_manual_corrections: list[ManualReviewCorrection] = Field(default_factory=list)
    review_error: str | None = None
    review_applied: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="before")
    @classmethod
    def reset_legacy_sentence_review(cls, value: Any) -> Any:
        """Keep old jobs visible, but require a fresh word-level review."""
        if not isinstance(value, dict):
            return value
        if value.get("minutes") and not value.get("minutes_versions"):
            value = dict(value)
            value["minutes_versions"] = [{
                "content": value["minutes"],
                "created_at": value.get("updated_at") or value.get("created_at")
                or datetime.now(UTC),
                "source": "legacy",
            }]
        review_items = value.get("review_items")
        has_sentence_review = isinstance(review_items, list) and any(
            isinstance(item, dict) and "original_text" in item
            for item in review_items
        )
        if not has_sentence_review:
            return value
        migrated = dict(value)
        migrated.update(
            review_status=ReviewStatus.idle,
            review_stage="需重新运行词级校对",
            review_progress=0,
            review_items=[],
            review_manual_corrections=[],
            review_error=None,
        )
        return migrated

    @property
    def compression_ratio(self) -> float | None:
        if not self.original_duration_seconds or self.compressed_duration_seconds is None:
            return None
        return self.compressed_duration_seconds / self.original_duration_seconds

    @computed_field
    @property
    def usage_summary(self) -> AIUsageSummary:
        real_calls = [call for call in self.usage_calls if call.status != "mock"]
        text_calls = [call for call in real_calls if call.kind == "text"]
        asr_calls = [call for call in real_calls if call.kind == "asr"]

        def reported_sum(field: str) -> int | None:
            values = [getattr(call, field) for call in text_calls]
            known = [value for value in values if value is not None]
            return sum(known) if known else None

        durations = [
            call.audio_duration_seconds for call in asr_calls
            if call.status == "success" and call.audio_duration_seconds is not None
        ]
        return AIUsageSummary(
            call_count=len(self.usage_calls),
            text_call_count=len(text_calls),
            asr_call_count=len(asr_calls),
            mock_call_count=len(self.usage_calls) - len(real_calls),
            input_tokens=reported_sum("input_tokens"),
            output_tokens=reported_sum("output_tokens"),
            total_tokens=reported_sum("total_tokens"),
            cached_input_tokens=reported_sum("cached_input_tokens"),
            missing_text_usage_calls=sum(
                any(value is None for value in (
                    call.input_tokens, call.output_tokens, call.total_tokens,
                )) for call in text_calls
            ),
            asr_duration_seconds=round(sum(durations), 3) if durations else None,
            missing_asr_duration_calls=sum(
                call.status == "success" and call.audio_duration_seconds is None
                for call in asr_calls
            ),
            failed_call_count=sum(call.status != "success" for call in real_calls),
        )


class HealthResponse(BaseModel):
    ok: bool
    ffmpeg_available: bool
    ai_configured: bool
    ai_provider: str = "语音 / 文本 API"
    transcription_model: str
    summary_model: str
