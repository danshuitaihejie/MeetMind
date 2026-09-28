from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from app.ai import AIService
from app.media import MediaProcessor
from app.models import (
    ReviewCorrection,
    ReviewItem,
    ReviewStatus,
    TranscriptSegment,
)
from app.ocr import OCRProcessingError, OCRService
from app.store import JobStore


def _save_segments(path: Path, segments: list[TranscriptSegment]) -> None:
    path.write_text(
        json.dumps(
            [segment.model_dump(mode="json") for segment in segments],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _load_segments(path: Path) -> list[TranscriptSegment]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("校对时间轴格式错误")
    return [TranscriptSegment.model_validate(item) for item in payload]


def _timestamp(seconds: float) -> str:
    rounded = max(0, round(seconds))
    hours, remainder = divmod(rounded, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _build_timed_transcript(segments: list[TranscriptSegment]) -> str:
    lines: list[str] = []
    for segment in segments:
        speaker = f"说话人 {segment.speaker}" if segment.speaker else "说话人"
        lines.append(f"[{_timestamp(segment.start_seconds)}] {speaker}：{segment.text}")
    return "\n".join(lines)


def _term_window(segment: TranscriptSegment, term: str) -> tuple[float, float]:
    """Locate a suspicious term within word-level ASR tokens when possible."""
    normalized_term = "".join(term.split())
    if not normalized_term or not segment.tokens:
        return segment.start_seconds, segment.end_seconds
    for start_index in range(len(segment.tokens)):
        combined = ""
        for end_index in range(start_index, len(segment.tokens)):
            combined += "".join(segment.tokens[end_index].text.split())
            if combined == normalized_term:
                return (
                    segment.tokens[start_index].start_seconds,
                    segment.tokens[end_index].end_seconds,
                )
            if not normalized_term.startswith(combined):
                break
    return segment.start_seconds, segment.end_seconds


def review_job(
    job_id: str,
    input_path: Path,
    store: JobStore,
    media: MediaProcessor,
    ai: AIService,
    ocr: OCRService,
) -> None:
    job = store.get(job_id)
    if not job or not job.transcript:
        return

    review_dir = store.job_dir(job_id) / "review"
    try:
        if review_dir.exists():
            shutil.rmtree(review_dir)
        clips_dir = review_dir / "clips"
        frames_dir = review_dir / "frames"
        clips_dir.mkdir(parents=True)
        frames_dir.mkdir(parents=True)

        store.update(
            job_id,
            review_status=ReviewStatus.processing,
            review_stage="提取原速音频",
            review_progress=8,
            review_items=[],
            review_error=None,
        )
        review_audio = review_dir / "original_speed.mp3"
        media.compress(input_path, review_audio, speed=1.0, trim_silence=False)
        duration = media.probe_duration(review_audio)
        chunks = media.split_for_transcription(
            review_audio,
            review_dir / "chunks",
            duration,
        )

        segments: list[TranscriptSegment] = []
        offset = 0.0
        for chunk_index, chunk in enumerate(chunks, start=1):
            progress = 10 + round(chunk_index / len(chunks) * 42)
            store.update(
                job_id,
                review_stage=f"原速音频对齐 {chunk_index}/{len(chunks)}",
                review_progress=progress,
            )
            for segment in ai.transcribe_detailed(chunk):
                offset_tokens = [
                    token.model_copy(
                        update={
                            "start_seconds": round(token.start_seconds + offset, 3),
                            "end_seconds": round(token.end_seconds + offset, 3),
                        }
                    )
                    for token in segment.tokens
                ]
                segments.append(
                    TranscriptSegment(
                        index=len(segments),
                        start_seconds=round(segment.start_seconds + offset, 3),
                        end_seconds=round(segment.end_seconds + offset, 3),
                        text=segment.text,
                        speaker=segment.speaker,
                        tokens=offset_tokens,
                    )
                )
            offset += media.probe_duration(chunk)

        segments_path = review_dir / "segments.json"
        _save_segments(segments_path, segments)
        store.update(job_id, review_stage="定位疑似错字", review_progress=58)
        suggestions = ai.find_review_suggestions(segments, job.transcript, job.context)
        by_index = {segment.index: segment for segment in segments}
        items: list[ReviewItem] = []
        for suggestion in suggestions:
            segment = by_index.get(suggestion.segment_index)
            if not segment:
                continue
            term_start, term_end = _term_window(segment, suggestion.original_term)
            items.append(
                ReviewItem(
                    id=uuid.uuid4().hex[:12],
                    segment_index=segment.index,
                    start_seconds=term_start,
                    end_seconds=term_end,
                    speaker=segment.speaker,
                    context_text=segment.text,
                    original_term=suggestion.original_term.strip(),
                    suggested_term=suggestion.suggested_term.strip(),
                    confidence=suggestion.confidence,
                    reason=suggestion.reason.strip(),
                )
            )

        has_video = media.has_video(input_path)
        total = max(1, len(items))
        for item_index, item in enumerate(items, start=1):
            store.update(
                job_id,
                review_stage=f"生成核对片段 {item_index}/{len(items)}",
                review_progress=60 + round(item_index / total * 25),
            )
            media.extract_audio_clip(
                input_path,
                clips_dir / f"{item.id}.mp3",
                item.start_seconds,
                item.end_seconds,
            )
            if not has_video:
                continue

            middle = (item.start_seconds + item.end_seconds) / 2
            frame_times = [
                item.start_seconds,
                middle,
                max(item.start_seconds, item.end_seconds - 0.1),
            ]
            ocr_lines: list[str] = []
            for frame_time in frame_times:
                frame_path = frames_dir / f"{item.id}_{item.frame_count}.jpg"
                if not media.extract_frame(input_path, frame_path, frame_time):
                    continue
                item.frame_count += 1
                try:
                    ocr_lines.extend(ocr.recognize(frame_path))
                except OCRProcessingError:
                    # OCR is supporting evidence; audio review remains usable if OCR fails.
                    continue
            item.ocr_text = list(dict.fromkeys(ocr_lines))[:40]

        store.update(job_id, review_stage="融合 OCR 结果", review_progress=90)
        refined = {
            (suggestion.segment_index, suggestion.original_term): suggestion
            for suggestion in ai.refine_review_suggestions(items, job.context)
        }
        for item in items:
            suggestion = refined.get((item.segment_index, item.original_term))
            if suggestion:
                item.suggested_term = suggestion.suggested_term.strip()
                item.confidence = suggestion.confidence
                item.reason = suggestion.reason.strip()

        store.update(
            job_id,
            review_status=ReviewStatus.ready,
            review_stage="等待人工确认" if items else "未发现明显疑似错字",
            review_progress=100,
            review_items=items,
            review_error=None,
        )
    except Exception as exc:
        store.update(
            job_id,
            review_status=ReviewStatus.failed,
            review_stage="智能校对失败",
            review_error=str(exc),
        )


def apply_review_corrections(
    job_id: str,
    corrections: list[ReviewCorrection],
    store: JobStore,
    ai: AIService,
) -> None:
    job = store.get(job_id)
    if not job:
        return
    job_dir = store.job_dir(job_id)
    try:
        store.update(
            job_id,
            review_status=ReviewStatus.applying,
            review_stage="应用人工修正",
            review_progress=30,
            review_error=None,
        )
        segments = _load_segments(job_dir / "review" / "segments.json")
        items_by_id = {item.id: item for item in job.review_items}
        segments_by_index = {segment.index: segment for segment in segments}

        for correction in corrections:
            item = items_by_id.get(correction.item_id)
            if not item:
                continue
            replacement = correction.replacement.strip()
            if not replacement:
                continue
            segment = segments_by_index.get(item.segment_index)
            if segment and item.original_term in segment.text:
                segment.text = segment.text.replace(item.original_term, replacement, 1)
                item.correction_term = replacement

        original_transcript = job_dir / "transcript.original.txt"
        transcript_path = job_dir / "transcript.txt"
        if not original_transcript.exists() and transcript_path.exists():
            shutil.copy2(transcript_path, original_transcript)

        transcript = _build_timed_transcript(segments)
        transcript_path.write_text(transcript, encoding="utf-8")
        _save_segments(job_dir / "review" / "segments.corrected.json", segments)
        store.update(
            job_id,
            review_stage="根据修正重新生成纪要",
            review_progress=68,
            transcript=transcript,
            review_items=list(items_by_id.values()),
        )
        minutes = ai.summarize(transcript, job.context)
        (job_dir / "minutes.md").write_text(minutes, encoding="utf-8")
        store.update(
            job_id,
            minutes=minutes,
            review_status=ReviewStatus.completed,
            review_stage="校对已应用",
            review_progress=100,
            review_items=list(items_by_id.values()),
            review_error=None,
        )
    except Exception as exc:
        store.update(
            job_id,
            review_status=ReviewStatus.failed,
            review_stage="应用修正失败",
            review_error=str(exc),
        )
