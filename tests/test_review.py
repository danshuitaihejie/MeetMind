from __future__ import annotations

import json
from pathlib import Path

from app.models import (
    Job,
    JobStatus,
    ManualReviewCorrection,
    ReviewStatus,
    TranscriptSegment,
    TranscriptToken,
)
from app.review import apply_review_corrections, search_review_term
from app.store import JobStore


def test_manual_search_distinguishes_repeated_terms(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    review_dir = store.job_dir("repeated-term") / "review"
    review_dir.mkdir()
    segment = TranscriptSegment(
        index=0,
        start_seconds=1,
        end_seconds=3,
        text="项目和项目",
        tokens=[
            TranscriptToken(start_seconds=1, end_seconds=1.5, text="项目"),
            TranscriptToken(start_seconds=1.5, end_seconds=2, text="和"),
            TranscriptToken(start_seconds=2, end_seconds=2.5, text="项目"),
        ],
    )
    (review_dir / "segments.json").write_text(
        json.dumps([segment.model_dump(mode="json")], ensure_ascii=False),
        encoding="utf-8",
    )

    matches = search_review_term("repeated-term", "项目", store)

    assert [match.term_start for match in matches] == [0, 3]
    assert matches[0].start_seconds == 1
    assert matches[1].start_seconds == 2


def test_confirmed_correction_survives_summary_failure(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    store.create(Job(
        id="summary-fails", filename="meeting.wav", status=JobStatus.completed,
        transcript="确认第一版流程。", review_status=ReviewStatus.ready,
    ))
    job_dir = store.job_dir("summary-fails")
    (job_dir / "review").mkdir()
    (job_dir / "transcript.txt").write_text("确认第一版流程。", encoding="utf-8")
    segment = TranscriptSegment(
        index=0, start_seconds=0, end_seconds=2, text="确认第一版流程。",
    )
    (job_dir / "review" / "segments.json").write_text(
        json.dumps([segment.model_dump()]), encoding="utf-8",
    )

    class FailingAI:
        def with_usage_recorder(self, recorder, operation_override=None):
            return self

        def summarize(self, transcript: str, context: str) -> str:
            raise RuntimeError("temporary summary failure")

    apply_review_corrections(
        "summary-fails", [], [ManualReviewCorrection(
            segment_index=0, term_start=2, original_term="第一版", replacement="首版",
        )], store, FailingAI(),
    )

    assert store.get("summary-fails").review_status == ReviewStatus.failed
    reloaded = JobStore(tmp_path / "jobs")
    assert reloaded.corrections.apply("第一版上线") == "首版上线"
    assert reloaded.corrections.records()[0].context_text == "确认第一版流程。"


def test_legacy_confirmations_import_without_learning_unconfirmed_suggestions(
    tmp_path: Path,
) -> None:
    store = JobStore(tmp_path / "jobs")
    correction = ManualReviewCorrection(
        segment_index=0, term_start=0, original_term="第一版", replacement="首版",
    )
    store.create(Job(
        id="legacy-corrected", filename="meeting.wav", status=JobStatus.completed,
        transcript="首版流程。", review_status=ReviewStatus.completed,
        review_manual_corrections=[correction],
    ))
    store.create(Job(
        id="unconfirmed", filename="meeting.wav", status=JobStatus.completed,
        review_status=ReviewStatus.ready,
        review_manual_corrections=[ManualReviewCorrection(
            segment_index=0, term_start=0, original_term="待改词", replacement="新词",
        )],
    ))
    review_dir = store.job_dir("legacy-corrected") / "review"
    review_dir.mkdir()
    (review_dir / "segments.json").write_text(
        json.dumps([{"index": 0, "text": "第一版流程。"}]), encoding="utf-8",
    )

    restarted = JobStore(tmp_path / "jobs")
    restarted_again = JobStore(tmp_path / "jobs")

    assert restarted.corrections.apply("第一版和待改词") == "首版和待改词"
    assert len(restarted_again.corrections.records()) == 1
    assert restarted.corrections.records()[0].context_text == "第一版流程。"


def test_invalid_manual_correction_is_not_learned(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    store.create(Job(
        id="stale", filename="meeting.wav", status=JobStatus.completed,
        transcript="第一版流程。", review_status=ReviewStatus.ready,
    ))
    review_dir = store.job_dir("stale") / "review"
    review_dir.mkdir()
    segment = TranscriptSegment(index=0, start_seconds=0, end_seconds=2, text="第一版流程。")
    (review_dir / "segments.json").write_text(
        json.dumps([segment.model_dump()]), encoding="utf-8",
    )

    apply_review_corrections(
        "stale", [], [ManualReviewCorrection(
            segment_index=0, term_start=1, original_term="第一版", replacement="首版",
        )], store, None,
    )

    assert store.get("stale").review_status == ReviewStatus.failed
    assert store.get("stale").transcript == "第一版流程。"
    assert store.corrections.records() == []
