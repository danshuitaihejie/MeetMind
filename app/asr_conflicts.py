from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

from app.models import ReviewSuggestion, TranscriptSegment

_PAIR = re.compile(r"(?<![A-Za-z])(?=([A-Za-z]{4,})\s+([A-Za-z]{2,})\b)")
_WORD = re.compile(r"(?<![A-Za-z])[A-Za-z]{4,}(?![A-Za-z])")


def find_asr_conflicts(
    segments: list[TranscriptSegment], fast_transcript: str,
) -> list[ReviewSuggestion]:
    """Surface likely English name conflicts that a limited AI review may miss.

    A matching second word anchors the comparison (for example, pitch me /
    peach me). Nearby standalone repetitions of the same name are included.
    These are review candidates, never automatic corrections.
    """
    fast_pairs: dict[str, set[str]] = defaultdict(set)
    for match in _PAIR.finditer(fast_transcript):
        fast_pairs[match.group(2).casefold()].add(match.group(1))

    anchors: dict[tuple[str, str], list[float]] = defaultdict(list)
    for segment in segments:
        for match in _PAIR.finditer(segment.text):
            heard, next_word = match.group(1), match.group(2)
            for fast_word in fast_pairs.get(next_word.casefold(), ()):
                left, right = heard.casefold(), fast_word.casefold()
                if (
                    left == right or len(left) < 4
                    or abs(len(left) - len(right)) > 2
                    or left[0] != right[0] or left[-2:] != right[-2:]
                    or SequenceMatcher(None, left, right).ratio() < 0.6
                ):
                    continue
                anchors[(heard, fast_word)].append(segment.start_seconds)

    suggestions: list[ReviewSuggestion] = []
    for segment in segments:
        for match in _WORD.finditer(segment.text):
            heard = match.group()
            alternatives = {
                fast_word for (wrong, fast_word), times in anchors.items()
                if wrong.casefold() == heard.casefold()
                and any(abs(segment.start_seconds - time) <= 30 for time in times)
            }
            if len(alternatives) != 1:
                continue
            fast_word = alternatives.pop()
            suggestions.append(ReviewSuggestion(
                segment_index=segment.index,
                original_term=heard,
                suggested_term=fast_word,
                confidence=0.7,
                reason="快速转写与原速转写对该英文名称有冲突，请结合原声和画面确认。",
            ))
    return suggestions[:12]
