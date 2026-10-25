from __future__ import annotations

import json
from pathlib import Path

from app.asr_conflicts import find_asr_conflicts
from app.models import (
    Job,
    JobStatus,
    ManualReviewCorrection,
    ReviewCorrection,
    ReviewItem,
    ReviewStatus,
    ReviewSubmission,
    TranscriptSegment,
    TranscriptToken,
)
from app.review import apply_review_corrections, review_job, search_review_term
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


def test_agent_flag_correction_targets_selected_occurrence(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    item = ReviewItem(
        id="second-project", segment_index=0, term_start=3,
        start_seconds=2, end_seconds=2.5, context_text="项目和项目",
        original_term="项目", suggested_term="工程", confidence=0,
        reason="第二处待核对", source="agent",
    )
    store.create(Job(
        id="repeated", filename="meeting.wav", status=JobStatus.completed,
        transcript="项目和项目", review_status=ReviewStatus.ready, review_items=[item],
    ))
    review_dir = store.job_dir("repeated") / "review"
    review_dir.mkdir()
    segment = TranscriptSegment(index=0, start_seconds=0, end_seconds=3, text="项目和项目")
    (review_dir / "segments.json").write_text(
        json.dumps([segment.model_dump()]), encoding="utf-8",
    )
    (store.job_dir("repeated") / "transcript.txt").write_text("项目和项目", encoding="utf-8")

    class SummaryAI:
        def with_language(self, language):
            return self

        def with_usage_recorder(self, recorder, operation_override=None):
            return self

        def summarize(self, transcript: str, context: str) -> str:
            return transcript

    apply_review_corrections(
        "repeated", [ReviewCorrection(item_id=item.id, replacement="工程")], [], store,
        SummaryAI(),
    )

    assert "项目和工程" in store.get("repeated").transcript
    record = store.corrections.records()[0]
    assert (record.term_start, record.source) == (3, "agent")


def test_confirmed_correction_survives_summary_failure(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    store.create(Job(
        id="summary-fails", filename="meeting.wav", status=JobStatus.completed,
        transcript="确认第一版流程。", review_status=ReviewStatus.ready,
    ))
    store.save_minutes("summary-fails", "# 原始纪要")
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
    assert store.get("summary-fails").minutes == "# 原始纪要"
    assert len(store.get("summary-fails").minutes_versions) == 1
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


def test_fast_asr_name_conflict_includes_nearby_repetitions() -> None:
    segments = [
        TranscriptSegment(index=0, start_seconds=8, end_seconds=9, text="叫做peach的skill"),
        TranscriptSegment(index=1, start_seconds=10, end_seconds=11, text="peach me"),
        TranscriptSegment(index=2, start_seconds=13, end_seconds=14, text="一个典型的peach me"),
        TranscriptSegment(index=3, start_seconds=90, end_seconds=91, text="我想吃peach"),
    ]

    found = find_asr_conflicts(segments, "有个 skill pitch me；典型的 pitch me")

    assert [(item.segment_index, item.original_term, item.suggested_term)
            for item in found] == [(0, "peach", "pitch"), (1, "peach", "pitch"),
                                  (2, "peach", "pitch")]


def test_review_submission_accepts_all_model_and_conflict_candidates() -> None:
    submission = ReviewSubmission(corrections=[
        ReviewCorrection(item_id=f"candidate-{index}", replacement="confirmed")
        for index in range(24)
    ])

    assert len(submission.corrections) == 24


def test_review_uses_later_video_frame_for_asr_conflict(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    store.create(Job(
        id="pitch-video", filename="meeting.mov", status=JobStatus.completed,
        transcript="我有一个 skill pitch me",
    ))
    source = tmp_path / "source.mov"
    source.write_bytes(b"video")

    class Media:
        frame_times: list[float] = []

        def compress(self, source, destination, **kwargs):
            destination.write_bytes(b"audio")

        def probe_duration(self, path):
            return 20

        def split_for_transcription(self, source, directory, duration):
            directory.mkdir()
            chunk = directory / "chunk.mp3"
            chunk.write_bytes(b"audio")
            return [chunk]

        def has_video(self, source):
            return True

        def extract_audio_clip(self, source, destination, start, end):
            destination.write_bytes(b"audio")

        def extract_frame(self, source, destination, at_seconds):
            self.frame_times.append(at_seconds)
            destination.write_bytes(b"frame")
            return True

    class AI:
        def with_language(self, language):
            return self

        def with_usage_recorder(self, recorder):
            return self

        def transcribe_detailed(self, chunk):
            return [TranscriptSegment(
                index=0, start_seconds=10, end_seconds=10.5, text="peach me",
                tokens=[
                    TranscriptToken(start_seconds=10, end_seconds=10.3, text="peach"),
                    TranscriptToken(start_seconds=10.3, end_seconds=10.5, text="me"),
                ],
            )]

        def find_review_suggestions(self, *args):
            return []

        def refine_review_suggestions(self, *args):
            return []

    class OCR:
        def recognize(self, path):
            return [f"unrelated {index}" for index in range(45)] + (
                ["/pitch-me"] if media.frame_times[-1] >= 12 else []
            )

    media = Media()
    review_job("pitch-video", source, store, media, AI(), OCR())

    job = store.get("pitch-video")
    assert job.review_status == ReviewStatus.ready
    assert len(job.review_items) == 1
    item = job.review_items[0]
    assert (item.original_term, item.suggested_term, item.requires_confirmation) == (
        "peach", "pitch", True,
    )
    assert "/pitch-me" in item.ocr_text
    assert item.confidence == 0.95
    assert any(time >= 12 for time in media.frame_times)

    apply_review_corrections("pitch-video", [], [], store, None)
    assert store.get("pitch-video").review_status == ReviewStatus.ready
    assert store.get("pitch-video").transcript == "我有一个 skill pitch me"

    class SummaryAI:
        def with_language(self, language):
            return self

        def with_usage_recorder(self, recorder, operation_override=None):
            return self

        def summarize(self, transcript, context):
            return transcript

    apply_review_corrections(
        "pitch-video", [ReviewCorrection(item_id=item.id, replacement="pitch")], [],
        store, SummaryAI(),
    )
    assert store.get("pitch-video").review_status == ReviewStatus.completed
    assert "pitch me" in store.get("pitch-video").transcript
    assert store.corrections.records()[0].source == "asr_conflict"
    assert JobStore(tmp_path / "jobs").corrections.apply("peach fruit") == "peach fruit"
