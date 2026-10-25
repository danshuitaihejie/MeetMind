from __future__ import annotations

from pathlib import Path

from app.corrections import CorrectionMemory, CorrectionRecord
from app.models import TranscriptSegment, TranscriptToken


def record(
    original: str,
    replacement: str,
    *,
    job_id: str = "job-1",
    segment_index: int = 0,
    term_start: int = 0,
    context: str = "上下文",
) -> CorrectionRecord:
    return CorrectionRecord(
        job_id=job_id,
        segment_index=segment_index,
        term_start=term_start,
        original_term=original,
        replacement=replacement,
        context_text=context,
        source="manual",
    )


def test_records_survive_restart_and_remember_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "data" / "corrections.sqlite3"
    memory = CorrectionMemory(path)
    correction = record("Meet Mine", "MeetMind")

    memory.remember([correction, correction])
    restarted = CorrectionMemory(path)

    assert restarted.records() == [correction]
    assert restarted.apply("Meet Mine 产品") == "MeetMind 产品"


def test_conflicting_replacements_require_manual_confirmation(tmp_path: Path) -> None:
    memory = CorrectionMemory(tmp_path / "corrections.sqlite3")
    memory.remember(
        [
            record("Meet Mine", "MeetMind", job_id="job-1"),
            record("Meet Mine", "Meet Mine", job_id="job-2"),
        ]
    )

    assert memory.apply("Meet Mine") == "Meet Mine"


def test_asr_conflict_does_not_become_a_global_word_replacement(tmp_path: Path) -> None:
    path = tmp_path / "corrections.sqlite3"
    memory = CorrectionMemory(path)
    correction = record("peach", "pitch")
    memory.remember([CorrectionRecord(
        job_id=correction.job_id,
        segment_index=correction.segment_index,
        term_start=correction.term_start,
        original_term=correction.original_term,
        replacement=correction.replacement,
        context_text=correction.context_text,
        source="asr_conflict",
    )])

    assert CorrectionMemory(path).apply("peach fruit") == "peach fruit"


def test_single_character_and_english_substrings_are_not_replaced(
    tmp_path: Path,
) -> None:
    memory = CorrectionMemory(tmp_path / "corrections.sqlite3")
    memory.remember(
        [
            record("错", "对"),
            record("cat", "dog", job_id="job-2"),
        ]
    )

    assert memory.apply("错 cat concatenate scat cat!") == "错 dog concatenate scat dog!"


def test_longest_match_wins_and_replacements_do_not_cascade(tmp_path: Path) -> None:
    memory = CorrectionMemory(tmp_path / "corrections.sqlite3")
    memory.remember(
        [
            record("Meet", "Hello", job_id="job-1"),
            record("Meet Mind", "Meet", job_id="job-2"),
            record("Hello", "Goodbye", job_id="job-3"),
        ]
    )

    assert memory.apply("Meet Mind / Meet") == "Meet / Hello"


def test_apply_segments_merges_cross_token_correction_and_keeps_audio_window(
    tmp_path: Path,
) -> None:
    memory = CorrectionMemory(tmp_path / "corrections.sqlite3")
    memory.remember([record("MeetMine", "MeetMind")])
    source = TranscriptSegment(
        index=0,
        start_seconds=1,
        end_seconds=3,
        text="MeetMine",
        tokens=[
            TranscriptToken(start_seconds=1.1, end_seconds=1.5, text="Meet"),
            TranscriptToken(start_seconds=1.5, end_seconds=2.2, text="Mine"),
        ],
    )

    corrected = memory.apply_segments([source])[0]

    assert corrected.text == "MeetMind"
    assert len(corrected.tokens) == 1
    assert corrected.tokens[0].text == "MeetMind"
    assert corrected.tokens[0].start_seconds == 1.1
    assert corrected.tokens[0].end_seconds == 2.2
    assert source.text == "MeetMine"
    assert [token.text for token in source.tokens] == ["Meet", "Mine"]
