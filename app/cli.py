"""Local, JSON-speaking CLI for automation and agent integrations."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.ai import AIService
from app.config import Settings
from app.media import MediaProcessor
from app.models import Job, JobStatus, ReviewCorrection, ReviewItem, ReviewStatus, ReviewSubmission
from app.ocr import OCRService
from app.pipeline import process_job
from app.review import apply_review_corrections, review_job, search_review_term
from app.store import JobStore
from app.validation import ALLOWED_EXTENSIONS, MAX_CONTEXT_CHARS, SPEED_OPTIONS


class CLIError(Exception):
    pass


class JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        _emit({"error": message, "code": "invalid_arguments"}, sys.stderr)
        raise SystemExit(2)


def _emit(value: Any, stream: Any = None) -> None:
    print(json.dumps(value, ensure_ascii=False, default=str), file=stream or sys.stdout)


def _parser() -> JSONArgumentParser:
    parser = JSONArgumentParser(prog="meetmind", description="本地处理会议文件，结果以 JSON 输出")
    parser.add_argument("--data-dir", type=Path, help="任务数据目录（默认读取 MEETMIND_DATA_DIR）")
    commands = parser.add_subparsers(dest="command", parser_class=JSONArgumentParser)

    serve = commands.add_parser("serve", help="启动网页服务")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=18473)
    serve.add_argument("--reload", action="store_true", help="代码变化时自动重启")

    process = commands.add_parser("process", help="同步处理本地音视频文件")
    process.add_argument("file", type=Path)
    process.add_argument("--speed", type=float, choices=SPEED_OPTIONS, default=1.5)
    process.add_argument("--language", choices=("en", "zh"), default="en")
    process.add_argument("--no-trim-silence", action="store_true")
    context = process.add_mutually_exclusive_group()
    context.add_argument("--context", default="", help="会议背景文字")
    context.add_argument("--context-file", type=Path, help="从 UTF-8 文件读取会议背景")

    commands.add_parser("list", aliases=["jobs"], help="列出已保存的任务")
    show = commands.add_parser("show", help="查询任务、结果与产物路径")
    show.add_argument("job_id")
    pending = commands.add_parser("pending", help="只列出仍待确认的疑似词和证据")
    pending.add_argument("job_id")
    retry = commands.add_parser("retry", help="同步重试失败的任务")
    retry.add_argument("job_id")
    review = commands.add_parser("review", help="同步执行智能校对")
    review.add_argument("job_id")
    search = commands.add_parser("search", help="在校对时间轴中查找词语")
    search.add_argument("job_id")
    search.add_argument("term")
    flag = commands.add_parser("flag", help="把 agent 无法确定的词加入人工待确认列表")
    flag.add_argument("job_id")
    flag.add_argument("term", help="search 返回的 original_term")
    flag.add_argument("--segment-index", type=int, required=True)
    flag.add_argument("--term-start", type=int, required=True)
    flag.add_argument("--suggested", default="", help="可选的候选写法，不会自动应用")
    flag.add_argument("--reason", default="Agent 标记，等待人工确认")
    apply = commands.add_parser("apply", help="应用校对 JSON 并重新生成纪要")
    apply.add_argument("job_id")
    apply.add_argument("--input", type=Path, required=True, help="ReviewSubmission JSON 文件")
    return parser


def _require_job(store: JobStore, job_id: str) -> Job:
    job = store.get(job_id)
    if job is None:
        raise CLIError("任务不存在")
    return job


def _source_path(store: JobStore, job_id: str) -> Path:
    paths = sorted(store.job_dir(job_id).glob("source.*"))
    if not paths:
        raise CLIError("原始文件已不存在")
    return paths[0]


def _job_payload(job: Job, store: JobStore) -> dict[str, Any]:
    directory = store.job_dir(job.id)
    candidates = {
        "source": next(iter(sorted(directory.glob("source.*"))), None),
        "audio": directory / "compressed.mp3",
        "transcript": directory / "transcript.txt",
        "minutes": directory / "minutes.md",
        "review_audio": directory / "review" / "original_speed.mp3",
        "review_segments": directory / "review" / "segments.json",
    }
    payload = job.model_dump(mode="json")
    payload["artifacts"] = {
        name: str(path.resolve()) for name, path in candidates.items()
        if path is not None and path.is_file()
    }
    payload["pending_review_count"] = sum(
        item.correction_term is None for item in job.review_items
    )
    for item in payload["review_items"]:
        review_dir = directory / "review"
        clip = review_dir / "clips" / f"{item['id']}.mp3"
        frames = [
            review_dir / "frames" / f"{item['id']}_{index}.jpg"
            for index in range(item["frame_count"])
        ]
        item["evidence"] = {
            "audio": str(clip.resolve()) if clip.is_file() else None,
            "frames": [str(frame.resolve()) for frame in frames if frame.is_file()],
        }
    return payload


def _process(args: argparse.Namespace, settings: Settings, store: JobStore) -> Job:
    source = args.file.expanduser().resolve()
    if not source.is_file():
        raise CLIError("输入文件不存在或不是普通文件")
    if source.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise CLIError("不支持此文件格式")
    if source.stat().st_size > settings.max_upload_mb * 1024 * 1024:
        raise CLIError(f"文件不能超过 {settings.max_upload_mb} MB")
    context = (
        sys.stdin.read() if args.context_file == Path("-")
        else args.context_file.read_text(encoding="utf-8") if args.context_file
        else args.context
    )
    if len(context) > MAX_CONTEXT_CHARS:
        raise CLIError(f"会议背景不能超过 {MAX_CONTEXT_CHARS} 个字符")
    if not MediaProcessor.available():
        raise CLIError("未安装 FFmpeg/FFprobe")
    if not settings.ai_configured:
        raise CLIError("语音和文本 API 未配置完整；请检查地址、密钥和格式")

    job_id = uuid.uuid4().hex
    directory = store.job_dir(job_id)
    input_path = directory / f"source{source.suffix.lower()}"
    try:
        shutil.copyfile(source, input_path)
        store.create(Job(
            id=job_id,
            filename=source.name,
            speed=args.speed,
            trim_silence=not args.no_trim_silence,
            context=context.strip(),
            language=args.language,
            original_size_bytes=source.stat().st_size,
        ))
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    process_job(job_id, input_path, store, MediaProcessor(), AIService(settings))
    return _require_job(store, job_id)


def _retry(job_id: str, settings: Settings, store: JobStore) -> Job:
    job = _require_job(store, job_id)
    if job.status != JobStatus.failed:
        raise CLIError("只有失败的任务可以重新处理")
    source = _source_path(store, job_id)
    if not MediaProcessor.available():
        raise CLIError("未安装 FFmpeg/FFprobe")
    if not settings.ai_configured:
        raise CLIError("语音和文本 API 未配置完整；请检查地址、密钥和格式")
    for name in ("transcript.txt", "minutes.md"):
        (store.job_dir(job_id) / name).unlink(missing_ok=True)
    store.update(
        job_id,
        status=JobStatus.queued,
        stage="等待重新处理",
        progress=0,
        transcript=None,
        minutes=None,
        error=None,
        review_status=ReviewStatus.idle,
        review_stage="",
        review_progress=0,
        review_items=[],
        review_manual_corrections=[],
        review_error=None,
        review_applied=False,
    )
    process_job(job_id, source, store, MediaProcessor(), AIService(settings))
    return _require_job(store, job_id)


def _review(job_id: str, settings: Settings, store: JobStore) -> Job:
    job = _require_job(store, job_id)
    if job.status != JobStatus.completed or not job.transcript:
        raise CLIError("会议完成转写后才能进行智能校对")
    if job.review_status in {ReviewStatus.processing, ReviewStatus.applying}:
        raise CLIError("智能校对正在处理中")
    source = _source_path(store, job_id)
    review_job(job_id, source, store, MediaProcessor(), AIService(settings), OCRService())
    return _require_job(store, job_id)


def _search(job_id: str, term: str, store: JobStore) -> list[dict[str, Any]]:
    job = _require_job(store, job_id)
    if job.review_status not in {ReviewStatus.ready, ReviewStatus.completed}:
        raise CLIError("请先运行智能校对以生成词级时间轴")
    term = term.strip()
    if not term or len(term) > 100:
        raise CLIError("查找词长度必须为 1 到 100 个字符")
    try:
        audio = store.job_dir(job_id) / "review" / "original_speed.mp3"
        audio_path = str(audio.resolve()) if audio.is_file() else None
        return [
            {**match.model_dump(mode="json"), "audio": audio_path}
            for match in search_review_term(job_id, term, store)
        ]
    except (OSError, ValueError) as exc:
        raise CLIError("词级时间轴不可用，请重新运行智能校对") from exc


def _flag(args: argparse.Namespace, store: JobStore) -> Job:
    job = _require_job(store, args.job_id)
    matches = _search(args.job_id, args.term, store)
    match = next(
        (
            entry for entry in matches
            if entry["segment_index"] == args.segment_index
            and entry["term_start"] == args.term_start
        ),
        None,
    )
    if match is None:
        raise CLIError("词语位置已失效，请重新运行 search")
    if len(args.suggested) > 100 or len(args.reason) > 4000:
        raise CLIError("候选词不能超过 100 字，原因不能超过 4000 字")
    if any(
        item.segment_index == args.segment_index
        and item.term_start == args.term_start
        and item.original_term == match["original_term"]
        for item in job.review_items
    ):
        raise CLIError("该位置已在待确认列表中")

    item = ReviewItem(
        id=uuid.uuid4().hex[:12],
        segment_index=match["segment_index"],
        term_start=match["term_start"],
        start_seconds=match["start_seconds"],
        end_seconds=match["end_seconds"],
        context_text=match["context_text"],
        original_term=match["original_term"],
        suggested_term=args.suggested.strip(),
        confidence=0,
        reason=args.reason.strip() or "Agent 标记，等待人工确认",
        source="agent",
    )
    clip = store.job_dir(job.id) / "review" / "clips" / f"{item.id}.mp3"
    MediaProcessor.extract_audio_clip(
        _source_path(store, job.id), clip, item.start_seconds, item.end_seconds
    )
    job.review_items.append(item)
    return store.update(
        job.id,
        review_items=job.review_items,
        review_status=ReviewStatus.ready,
        review_stage="等待人工确认",
        review_progress=100,
    )


def _apply(job_id: str, input_path: Path, settings: Settings, store: JobStore) -> Job:
    job = _require_job(store, job_id)
    if job.review_status not in {ReviewStatus.ready, ReviewStatus.completed}:
        raise CLIError("当前没有可应用的校对结果")
    raw = sys.stdin.read() if input_path == Path("-") else input_path.read_text(encoding="utf-8")
    submission = ReviewSubmission.model_validate_json(raw)
    known_ids = {item.id for item in job.review_items}
    if any(item.item_id not in known_ids for item in submission.corrections):
        raise CLIError("校对项不存在或已过期")
    # CLI submissions are incremental. Keep earlier confirmed decisions when an agent
    # later resolves another item; the web form still submits its complete selection.
    corrections = {
        item.id: ReviewCorrection(item_id=item.id, replacement=item.correction_term)
        for item in job.review_items if item.correction_term is not None
    }
    corrections.update({item.item_id: item for item in submission.corrections})
    manual = {
        (item.segment_index, item.term_start, item.original_term): item
        for item in job.review_manual_corrections
    }
    manual.update({
        (item.segment_index, item.term_start, item.original_term): item
        for item in submission.manual_corrections
    })
    merged = ReviewSubmission(
        corrections=list(corrections.values()), manual_corrections=list(manual.values())
    )
    apply_review_corrections(
        job_id, merged.corrections, merged.manual_corrections, store, AIService(settings)
    )
    return _require_job(store, job_id)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command in {None, "serve"}:
        if args.data_dir is not None:
            os.environ["MEETMIND_DATA_DIR"] = str(args.data_dir)
        import uvicorn

        uvicorn.run(
            "app.main:app",
            host=getattr(args, "host", "127.0.0.1"),
            port=getattr(args, "port", 18473),
            reload=args.command is None or getattr(args, "reload", False),
        )
        return 0

    try:
        settings = Settings.from_env()
        if args.data_dir is not None:
            settings.data_dir = args.data_dir.expanduser().resolve()
        store = JobStore(settings.data_dir / "jobs")
        if args.command == "process":
            result = _process(args, settings, store)
        elif args.command in {"list", "jobs"}:
            _emit([_job_payload(job, store) for job in store.list()])
            return 0
        elif args.command == "show":
            result = _require_job(store, args.job_id)
        elif args.command == "pending":
            job = _require_job(store, args.job_id)
            payload = _job_payload(job, store)
            _emit({
                "job_id": job.id,
                "review_status": job.review_status,
                "pending_review_count": payload["pending_review_count"],
                "items": [
                    item for item in payload["review_items"] if item["correction_term"] is None
                ],
            })
            return 0
        elif args.command == "retry":
            result = _retry(args.job_id, settings, store)
        elif args.command == "review":
            result = _review(args.job_id, settings, store)
        elif args.command == "search":
            _emit(_search(args.job_id, args.term, store))
            return 0
        elif args.command == "flag":
            result = _flag(args, store)
        elif args.command == "apply":
            result = _apply(args.job_id, args.input, settings, store)
        else:
            raise CLIError("未知命令")
        _emit(_job_payload(result, store))
        if args.command != "show" and (
            result.status == JobStatus.failed or result.review_status == ReviewStatus.failed
        ):
            return 1
        return 0
    except ValidationError as exc:
        _emit(
            {"error": exc.errors(include_input=False), "code": "invalid_input"}, sys.stderr
        )
        return 2
    except (CLIError, OSError, UnicodeError, ValueError) as exc:
        _emit({"error": str(exc), "code": "cli_error"}, sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
