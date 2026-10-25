from __future__ import annotations

import json
import re
import threading
from difflib import SequenceMatcher
from pathlib import Path

from app.ai import AIService
from app.media import MediaProcessor
from app.models import ChatPassage, Job, TranscriptSegment
from app.store import JobStore

_alignment_lock = threading.RLock()


def source_path(store: JobStore, job: Job) -> Path:
    return store.job_dir(job.id) / f"source{Path(job.filename).suffix.lower()}"


def ensure_original_audio(store: JobStore, job: Job, media: MediaProcessor) -> Path:
    """Create an untrimmed, original-speed audio fallback without exposing partial files."""
    with _alignment_lock:
        original = source_path(store, job)
        if not original.is_file():
            raise FileNotFoundError(original)
        directory = store.job_dir(job.id) / "alignment"
        directory.mkdir(exist_ok=True)
        audio = directory / "original_speed.mp3"
        if not audio.is_file():
            temporary = directory / "original_speed.tmp.mp3"
            try:
                media.compress(original, temporary, speed=1.0, trim_silence=False)
                temporary.replace(audio)
            finally:
                temporary.unlink(missing_ok=True)
        return audio


def load_segments(store: JobStore, job: Job) -> list[TranscriptSegment]:
    for path in (
        store.job_dir(job.id) / "review" / "segments.corrected.json",
        store.job_dir(job.id) / "review" / "segments.json",
        store.job_dir(job.id) / "alignment" / "segments.json",
    ):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                segments = [TranscriptSegment.model_validate(item) for item in payload]
                if segments:
                    return segments
        except (OSError, ValueError):
            continue
    return []


def ensure_segments(
    store: JobStore, job: Job, media: MediaProcessor, ai: AIService,
) -> list[TranscriptSegment]:
    """Build an original-speed time axis once for a meeting lacking review data."""
    with _alignment_lock:
        existing = load_segments(store, job)
        if existing:
            return existing
        if not source_path(store, job).is_file():
            return []
        directory = store.job_dir(job.id) / "alignment"
        directory.mkdir(exist_ok=True)
        audio = ensure_original_audio(store, job, media)
        duration = media.probe_duration(audio)
        chunks = media.split_for_transcription(audio, directory / "chunks", duration)
        timed: list[TranscriptSegment] = []
        offset = 0.0
        for chunk in chunks:
            for segment in ai.transcribe_detailed(chunk):
                timed.append(segment.model_copy(update={
                    "index": len(timed),
                    "start_seconds": round(segment.start_seconds + offset, 3),
                    "end_seconds": round(segment.end_seconds + offset, 3),
                    "tokens": [token.model_copy(update={
                        "start_seconds": round(token.start_seconds + offset, 3),
                        "end_seconds": round(token.end_seconds + offset, 3),
                    }) for token in segment.tokens],
                }))
            offset += media.probe_duration(chunk)
        if timed:
            target = directory / "segments.json"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(
                [segment.model_dump(mode="json") for segment in timed], ensure_ascii=False,
            ), encoding="utf-8")
            temporary.replace(target)
        return timed


def locate_text(text: str, segments: list[TranscriptSegment]) -> ChatPassage | None:
    """Map a displayed transcript excerpt to the best aligned original-media segment."""
    from app.chat import _terms

    words = _terms(text)
    if not words:
        return None
    ranked = sorted(
        segments,
        key=lambda segment: len(words & _terms(segment.text)),
        reverse=True,
    )
    if not ranked or len(words.intersection(_terms(ranked[0].text))) < min(2, len(words)):
        return None
    normalized_text = re.sub(r"[^a-z0-9\u3400-\u9fff]", "", text.casefold())
    if not normalized_text:
        return None
    scored = []
    for segment in ranked[:12]:
        normalized_segment = re.sub(
            r"[^a-z0-9\u3400-\u9fff]", "", segment.text.casefold(),
        )
        longest = SequenceMatcher(None, normalized_text, normalized_segment,
                                  autojunk=False).find_longest_match().size
        scored.append((longest, len(words & _terms(segment.text)), segment))
    longest, _, segment = max(scored, key=lambda item: item[:2])
    if longest < min(4, len(normalized_text)):
        return None
    return ChatPassage(
        text=segment.text,
        start_seconds=segment.start_seconds,
        end_seconds=segment.end_seconds,
    )
