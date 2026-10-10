from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.models import TranscriptSegment, TranscriptToken


@dataclass(frozen=True)
class CorrectionRecord:
    job_id: str
    segment_index: int
    term_start: int
    original_term: str
    replacement: str
    context_text: str
    source: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class CorrectionMemory:
    """Persist explicit user confirmations and reuse unambiguous term mappings."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS corrections (
                    id INTEGER PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    segment_index INTEGER NOT NULL,
                    term_start INTEGER NOT NULL,
                    original_term TEXT NOT NULL,
                    replacement TEXT NOT NULL,
                    context_text TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(job_id, segment_index, term_start, original_term, replacement)
                )"""
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def remember(self, records: list[CorrectionRecord]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """INSERT OR IGNORE INTO corrections
                   (job_id, segment_index, term_start, original_term, replacement,
                    context_text, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        record.job_id, record.segment_index, record.term_start,
                        record.original_term, record.replacement.strip(),
                        record.context_text, record.source, record.created_at,
                    )
                    for record in records
                    if record.original_term.strip() and record.replacement.strip()
                ],
            )

    def records(self) -> list[CorrectionRecord]:
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """SELECT job_id, segment_index, term_start, original_term, replacement,
                          context_text, source, created_at FROM corrections ORDER BY id"""
            ).fetchall()
        return [CorrectionRecord(**dict(row)) for row in rows]

    def _rules(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT original_term, MIN(replacement) FROM corrections
                   GROUP BY original_term HAVING COUNT(DISTINCT replacement) = 1"""
            ).fetchall()
        return {
            original: replacement
            for original, replacement in rows
            if len(original.strip()) > 1 and original != replacement
        }

    @staticmethod
    def _pattern(rules: dict[str, str]) -> re.Pattern[str] | None:
        patterns = []
        for term in sorted(rules, key=lambda value: (-len(value), value)):
            pattern = re.escape(term)
            if term[0].isascii() and (term[0].isalnum() or term[0] == "_"):
                pattern = r"(?<![A-Za-z0-9_])" + pattern
            if term[-1].isascii() and (term[-1].isalnum() or term[-1] == "_"):
                pattern += r"(?![A-Za-z0-9_])"
            patterns.append(pattern)
        return re.compile("|".join(patterns)) if patterns else None

    def apply(self, text: str, *, exclude: set[str] | None = None) -> str:
        rules = {
            term: value for term, value in self._rules().items()
            if term not in (exclude or ())
        }
        pattern = self._pattern(rules)
        # One pass prevents cascading rules from rewriting their own replacements.
        return pattern.sub(lambda match: rules[match.group()], text) if pattern else text

    def apply_segments(self, segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
        rules = self._rules()
        pattern = self._pattern(rules)
        result = [segment.model_copy(deep=True) for segment in segments]
        if not pattern:
            return result
        for segment in result:
            original = segment.text
            matches = list(pattern.finditer(original))
            if not matches:
                continue
            segment.text = pattern.sub(lambda match: rules[match.group()], original)
            segment.tokens = self._correct_tokens(segment.tokens, original, matches, rules)
        return result

    @staticmethod
    def _correct_tokens(
        tokens: list[TranscriptToken],
        text: str,
        matches: list[re.Match[str]],
        rules: dict[str, str],
    ) -> list[TranscriptToken]:
        # Merge tokens covered by a corrected phrase, retaining its original audio window.
        spans: list[tuple[int, int]] = []
        cursor = 0
        for token in tokens:
            start = text.find(token.text, cursor)
            if start < 0:
                return tokens
            spans.append((start, start + len(token.text)))
            cursor = spans[-1][1]
        groups: list[tuple[int, int]] = []
        for match in matches:
            affected = [
                index for index, (start, end) in enumerate(spans)
                if start < match.end() and end > match.start()
            ]
            if not affected:
                continue
            first, last = affected[0], affected[-1]
            if groups and first <= groups[-1][1]:
                groups[-1] = (groups[-1][0], max(last, groups[-1][1]))
            else:
                groups.append((first, last))
        corrected: list[TranscriptToken] = []
        cursor = 0
        for first, last in groups:
            corrected.extend(tokens[cursor:first])
            start, end = spans[first][0], spans[last][1]
            group_text = text[start:end]
            for match in reversed(matches):
                if start <= match.start() and match.end() <= end:
                    group_text = (
                        group_text[:match.start() - start] + rules[match.group()]
                        + group_text[match.end() - start:]
                    )
            corrected.append(tokens[first].model_copy(update={
                "text": group_text,
                "end_seconds": tokens[last].end_seconds,
            }))
            cursor = last + 1
        corrected.extend(tokens[cursor:])
        return corrected
