from __future__ import annotations

from pathlib import Path

from app.ai import AIService
from app.media import MediaProcessor
from app.models import JobStatus
from app.store import JobStore


def process_job(
    job_id: str,
    input_path: Path,
    store: JobStore,
    media: MediaProcessor,
    ai: AIService,
) -> None:
    job = store.get(job_id)
    if not job:
        return
    ai = ai.with_language(job.language).with_usage_recorder(
        lambda call: store.record_usage(job_id, call),
    )

    output_path = store.job_dir(job_id) / "compressed.mp3"
    try:
        store.update(
            job_id,
            status=JobStatus.processing,
            stage="读取媒体信息",
            progress=12,
            error=None,
        )
        original_duration = media.probe_duration(input_path)

        store.update(
            job_id,
            stage="提取并压缩音频",
            progress=28,
            original_duration_seconds=round(original_duration, 2),
        )
        media.compress(input_path, output_path, job.speed, job.trim_silence)
        compressed_duration = media.probe_duration(output_path)
        compressed_size = output_path.stat().st_size

        store.update(
            job_id,
            stage="准备语音转写",
            progress=52,
            compressed_duration_seconds=round(compressed_duration, 2),
            compressed_size_bytes=compressed_size,
        )
        chunks = media.split_for_transcription(
            output_path,
            store.job_dir(job_id) / "chunks",
            compressed_duration,
        )
        transcript_parts: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            progress = 52 + round(index / len(chunks) * 28)
            store.update(
                job_id,
                stage=f"语音转写 {index}/{len(chunks)}",
                progress=progress,
            )
            transcript_parts.append(ai.transcribe(chunk, job.context))
        raw_transcript = "\n\n".join(transcript_parts)
        store.update(job_id, stage="应用已确认的词语纠正", progress=82)
        transcript = store.corrections.apply(raw_transcript)
        if transcript != raw_transcript:
            (store.job_dir(job_id) / "transcript.original.txt").write_text(
                raw_transcript, encoding="utf-8"
            )
        (store.job_dir(job_id) / "transcript.txt").write_text(transcript, encoding="utf-8")

        store.update(job_id, stage="整理会议纪要", progress=84, transcript=transcript)
        minutes = ai.summarize(transcript, job.context)
        store.save_minutes(job_id, minutes)

        store.update(
            job_id,
            status=JobStatus.completed,
            stage="处理完成",
            progress=100,
            error=None,
        )
    except Exception as exc:  # Pipeline failures must be visible to the polling client.
        store.update(
            job_id,
            status=JobStatus.failed,
            stage="处理失败",
            error=str(exc),
        )
