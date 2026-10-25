from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path

from app.ai import AIService
from app.asr_conflicts import find_asr_conflicts
from app.corrections import CorrectionRecord
from app.media import MediaProcessor
from app.models import (
    ManualReviewCorrection,
    ManualReviewMatch,
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


def _term_window(
    segment: TranscriptSegment,
    term: str,
    occurrence: int = 0,
) -> tuple[float, float]:
    """Locate a suspicious term within word-level ASR tokens when possible."""
    normalized_term = "".join(term.split())
    if not normalized_term or not segment.tokens:
        return segment.start_seconds, segment.end_seconds
    matched_occurrences = 0
    for start_index in range(len(segment.tokens)):
        combined = ""
        for end_index in range(start_index, len(segment.tokens)):
            combined += "".join(segment.tokens[end_index].text.split())
            if combined == normalized_term:
                if matched_occurrences == occurrence:
                    return (
                        segment.tokens[start_index].start_seconds,
                        segment.tokens[end_index].end_seconds,
                    )
                matched_occurrences += 1
                break
            if not normalized_term.startswith(combined):
                break
    return segment.start_seconds, segment.end_seconds


def _find_occurrences(text: str, term: str) -> list[int]:
    if not term:
        return []
    starts: list[int] = []
    cursor = 0
    while True:
        index = text.find(term, cursor)
        if index < 0:
            return starts
        starts.append(index)
        cursor = index + len(term)


def _item_term_position(segment: TranscriptSegment | None, item: ReviewItem) -> int | None:
    if segment is None:
        return None
    position = (
        item.term_start if item.term_start is not None else segment.text.find(item.original_term)
    )
    if position < 0 or (
        segment.text[position:position + len(item.original_term)] != item.original_term
    ):
        return None
    return position


def _ocr_supports(term: str, line: str) -> bool:
    normalized_term = re.sub(r"[^a-z0-9]", "", term.casefold())
    normalized_line = re.sub(r"[^a-z0-9]", "", line.casefold())
    return len(normalized_term) >= 4 and normalized_term in normalized_line


def _select_ocr_lines(lines: list[str], original: str, suggested: str) -> list[str]:
    unique = list(dict.fromkeys(lines))
    # Small command labels often appear after many unrelated interface lines.
    return sorted(
        unique,
        key=lambda line: not (
            _ocr_supports(suggested, line) or _ocr_supports(original, line)
        ),
    )[:40]


def search_review_term(
    job_id: str,
    term: str,
    store: JobStore,
) -> list[ManualReviewMatch]:
    segments_path = store.job_dir(job_id) / "review" / "segments.json"
    segments = _load_segments(segments_path)
    matches: list[ManualReviewMatch] = []
    for segment in segments:
        for occurrence, term_start in enumerate(_find_occurrences(segment.text, term)):
            start_seconds, end_seconds = _term_window(segment, term, occurrence)
            matches.append(
                ManualReviewMatch(
                    segment_index=segment.index,
                    term_start=term_start,
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                    context_text=segment.text,
                    original_term=term,
                )
            )
            if len(matches) >= 30:
                return matches
    return matches


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
    ai = ai.with_language(job.language).with_usage_recorder(
        lambda call: store.record_usage(job_id, call),
    )

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
            review_applied=False,
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

        _save_segments(review_dir / "segments.original.json", segments)
        segments = store.corrections.apply_segments(segments)
        segments_path = review_dir / "segments.json"
        _save_segments(segments_path, segments)
        store.update(job_id, review_stage="定位疑似错字", review_progress=58)
        fast_path = store.job_dir(job_id) / "transcript.original.txt"
        fast_transcript = (
            store.corrections.apply(fast_path.read_text(encoding="utf-8"))
            if fast_path.is_file() else job.transcript
        )
        conflicts = find_asr_conflicts(segments, fast_transcript)
        suggestions = ai.find_review_suggestions(segments, fast_transcript, job.context)
        conflict_keys = {(item.segment_index, item.original_term) for item in conflicts}
        suggestions = [
            item for item in suggestions
            if (item.segment_index, item.original_term) not in conflict_keys
        ] + conflicts
        by_index = {segment.index: segment for segment in segments}
        items: list[ReviewItem] = []
        for suggestion in suggestions:
            segment = by_index.get(suggestion.segment_index)
            if not segment or suggestion.original_term.strip() not in segment.text:
                continue
            term_start, term_end = _term_window(segment, suggestion.original_term)
            items.append(
                ReviewItem(
                    id=uuid.uuid4().hex[:12],
                    segment_index=segment.index,
                    term_start=segment.text.find(suggestion.original_term.strip()),
                    start_seconds=term_start,
                    end_seconds=term_end,
                    speaker=segment.speaker,
                    context_text=segment.text,
                    original_term=suggestion.original_term.strip(),
                    suggested_term=suggestion.suggested_term.strip(),
                    confidence=suggestion.confidence,
                    reason=suggestion.reason.strip(),
                    requires_confirmation=(
                        suggestion.segment_index, suggestion.original_term
                    ) in conflict_keys,
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
            frame_times = (
                [item.start_seconds, middle, item.end_seconds + 2, item.end_seconds + 5]
                if item.requires_confirmation else
                [item.start_seconds, middle, max(item.start_seconds, item.end_seconds - 0.1)]
            )
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
            item.ocr_text = _select_ocr_lines(
                ocr_lines, item.original_term, item.suggested_term,
            )

        store.update(job_id, review_stage="融合 OCR 结果", review_progress=90)
        refined = {
            (suggestion.segment_index, suggestion.original_term): suggestion
            for suggestion in ai.refine_review_suggestions(
                [item for item in items if not item.requires_confirmation], job.context,
            )
        }
        for item in items:
            suggestion = refined.get((item.segment_index, item.original_term))
            if suggestion and not item.requires_confirmation:
                item.suggested_term = suggestion.suggested_term.strip()
                item.confidence = suggestion.confidence
                item.reason = suggestion.reason.strip()
            if item.requires_confirmation:
                if any(_ocr_supports(item.suggested_term, line) for line in item.ocr_text):
                    item.confidence = 0.95
                    evidence = "视频画面 OCR 也识别到快速转写中的名称。"
                else:
                    evidence = "画面暂未识别到该名称。"
                item.reason = (
                    f"快速转写与原速转写存在冲突；{evidence}"
                    "请听原声并查看画面后确认。"
                )

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
    manual_corrections: list[ManualReviewCorrection],
    store: JobStore,
    ai: AIService,
) -> None:
    job = store.get(job_id)
    if not job:
        return
    confirmed_ids = {correction.item_id for correction in corrections}
    unresolved = [
        item for item in job.review_items
        if item.requires_confirmation and item.correction_term is None
        and item.id not in confirmed_ids
        and not any(
            correction.segment_index == item.segment_index
            and correction.term_start == item.term_start
            and correction.original_term == item.original_term
            for correction in manual_corrections
        )
    ]
    if unresolved:
        store.update(
            job_id,
            review_status=ReviewStatus.ready,
            review_stage=f"请先确认 {len(unresolved)} 处两版转写冲突",
            review_error="两版转写冲突尚未确认；请听原声并查看视频画面。",
        )
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
        edits: dict[tuple[int, int, int], str] = {}

        for correction in corrections:
            item = items_by_id.get(correction.item_id)
            if not item:
                continue
            replacement = correction.replacement.strip()
            if not replacement:
                continue
            if replacement == item.original_term:
                # A confirmed "keep original" resolves the item without learning an identity rule.
                item.correction_term = replacement
                continue
            segment = segments_by_index.get(item.segment_index)
            position = _item_term_position(segment, item)
            if segment is not None and position is not None:
                term_start = position
                term_end = term_start + len(item.original_term)
                edits[(segment.index, term_start, term_end)] = replacement
                item.correction_term = replacement

        for correction in manual_corrections:
            segment = segments_by_index.get(correction.segment_index)
            term_end = correction.term_start + len(correction.original_term)
            if (
                not segment
                or segment.text[correction.term_start:term_end] != correction.original_term
            ):
                raise ValueError("手动校对位置已失效，请重新搜索该词")
            replacement = correction.replacement.strip()
            if not replacement:
                raise ValueError("修正词不能为空")
            edits[(segment.index, correction.term_start, term_end)] = replacement

        records: list[CorrectionRecord] = []
        conflict_spans: set[tuple[int, int]] = set()
        for item in items_by_id.values():
            if item.requires_confirmation:
                position = _item_term_position(
                    segments_by_index.get(item.segment_index), item,
                )
                if position is not None:
                    conflict_spans.add((item.segment_index, position))
        manual_corrections = [
            correction.model_copy(update={"learn_globally": False})
            if (correction.segment_index, correction.term_start) in conflict_spans
            else correction
            for correction in manual_corrections
        ]
        for (segment_index, term_start, term_end), replacement in sorted(edits.items()):
            segment = segments_by_index[segment_index]
            matching_manual = next(
                (
                    item for item in manual_corrections
                    if item.segment_index == segment_index and item.term_start == term_start
                ), None,
            )
            if (segment_index, term_start) in conflict_spans or (
                matching_manual is not None and not matching_manual.learn_globally
            ):
                source = "asr_conflict"
            elif matching_manual is not None:
                source = "manual"
            elif any(
                item.source == "agent" and item.segment_index == segment_index
                and _item_term_position(segment, item) == term_start
                for item in items_by_id.values()
            ):
                source = "agent"
            else:
                source = "suggested"
            records.append(CorrectionRecord(
                job_id=job_id,
                segment_index=segment_index,
                term_start=term_start,
                original_term=segment.text[term_start:term_end],
                replacement=replacement,
                context_text=segment.text,
                source=source,
            ))
        previous_edit: tuple[int, int, int] | None = None
        for edit in sorted(edits):
            if previous_edit and edit[0] == previous_edit[0] and edit[1] < previous_edit[2]:
                raise ValueError("修正位置重叠，请分别确认需要修改的词语")
            previous_edit = edit

        for item in items_by_id.values():
            segment = segments_by_index.get(item.segment_index)
            position = _item_term_position(segment, item)
            if segment is not None and position is not None:
                term_start = position
                edit = (segment.index, term_start, term_start + len(item.original_term))
                if edit in edits:
                    item.correction_term = edits[edit]

        for (segment_index, term_start, term_end), replacement in sorted(
            edits.items(),
            key=lambda entry: (entry[0][0], entry[0][1]),
            reverse=True,
        ):
            segment = segments_by_index[segment_index]
            segment.text = (
                segment.text[:term_start] + replacement + segment.text[term_end:]
            )

        original_transcript = job_dir / "transcript.original.txt"
        transcript_path = job_dir / "transcript.txt"
        if not original_transcript.exists() and transcript_path.exists():
            shutil.copy2(transcript_path, original_transcript)

        transcript = _build_timed_transcript(segments)
        transcript_path.write_text(transcript, encoding="utf-8")
        _save_segments(job_dir / "review" / "segments.corrected.json", segments)
        # Remember accepted edits even when the later summary request fails.
        store.corrections.remember(records)
        store.update(
            job_id,
            review_stage="根据修正重新生成纪要",
            review_progress=68,
            transcript=transcript,
            review_items=list(items_by_id.values()),
            review_manual_corrections=manual_corrections,
            review_applied=True,
        )
        ai = ai.with_language(job.language).with_usage_recorder(
            lambda call: store.record_usage(job_id, call),
            operation_override="summary_regeneration",
        )
        minutes = ai.summarize(transcript, job.context)
        store.save_minutes(job_id, minutes, regenerated=True)
        pending_count = sum(item.correction_term is None for item in items_by_id.values())
        store.update(
            job_id,
            review_status=ReviewStatus.ready if pending_count else ReviewStatus.completed,
            review_stage=(
                f"已应用修正，仍有 {pending_count} 项待确认" if pending_count else "校对已应用"
            ),
            review_progress=100,
            review_items=list(items_by_id.values()),
            review_manual_corrections=manual_corrections,
            review_error=None,
        )
    except Exception as exc:
        store.update(
            job_id,
            review_status=ReviewStatus.failed,
            review_stage="应用修正失败",
            review_error=str(exc),
        )
