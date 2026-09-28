from __future__ import annotations

import json
from pathlib import Path

from app.models import TranscriptSegment, TranscriptToken
from app.review import search_review_term
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
