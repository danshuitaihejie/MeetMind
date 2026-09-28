from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.ai import AIService
from app.config import Settings
from app.media import MediaProcessor
from app.models import (
    HealthResponse,
    Job,
    JobStatus,
    ManualReviewMatch,
    ReviewStatus,
    ReviewSubmission,
)
from app.ocr import OCRService
from app.pipeline import process_job
from app.review import apply_review_corrections, review_job, search_review_term
from app.store import JobStore

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ALLOWED_EXTENSIONS = {
    ".mp3",
    ".mp4",
    ".m4a",
    ".mov",
    ".mpeg",
    ".mpga",
    ".wav",
    ".webm",
    ".mkv",
    ".aac",
    ".flac",
    ".ogg",
}
SPEED_OPTIONS = {1.0, 1.25, 1.5, 1.75, 2.0}


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    store = JobStore(app_settings.data_dir / "jobs")
    media = MediaProcessor()
    ai = AIService(app_settings)
    ocr = OCRService()

    app = FastAPI(title="MeetMind", version="0.1.0")
    app.state.settings = app_settings
    app.state.store = store
    app.state.ocr = ocr
    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        ffmpeg_available = media.available()
        ai_configured = bool(app_settings.minimax_api_key or app_settings.mock_ai)
        return HealthResponse(
            ok=ffmpeg_available,
            ffmpeg_available=ffmpeg_available,
            ai_configured=ai_configured,
            ai_provider="MiniMax",
            transcription_model=app_settings.transcription_model,
            summary_model=app_settings.summary_model,
        )

    @app.get("/api/jobs", response_model=list[Job])
    def list_jobs() -> list[Job]:
        return store.list()

    @app.get("/api/jobs/{job_id}", response_model=Job)
    def get_job(job_id: str) -> Job:
        job = store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        return job

    @app.post("/api/jobs", response_model=Job, status_code=202)
    async def create_job(
        background_tasks: BackgroundTasks,
        file: Annotated[UploadFile, File()],
        speed: Annotated[float, Form()] = 1.5,
        trim_silence: Annotated[bool, Form()] = True,
        context: Annotated[str, Form()] = "",
    ) -> Job:
        if not media.available():
            raise HTTPException(status_code=503, detail="服务器未安装 FFmpeg/FFprobe")
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=415, detail="不支持此文件格式")
        if speed not in SPEED_OPTIONS:
            raise HTTPException(status_code=422, detail="加速倍率必须是 1、1.25、1.5、1.75 或 2")
        if len(context) > 4000:
            raise HTTPException(status_code=422, detail="会议背景不能超过 4000 个字符")

        job_id = uuid.uuid4().hex
        job_dir = store.job_dir(job_id)
        input_path = job_dir / f"source{suffix}"
        max_bytes = app_settings.max_upload_mb * 1024 * 1024
        size = 0
        try:
            with input_path.open("wb") as destination:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"文件不能超过 {app_settings.max_upload_mb} MB",
                        )
                    destination.write(chunk)
        except Exception:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
        finally:
            await file.close()

        job = Job(
            id=job_id,
            filename=Path(file.filename or f"recording{suffix}").name,
            content_type=file.content_type,
            speed=speed,
            trim_silence=trim_silence,
            context=context.strip(),
            original_size_bytes=size,
        )
        store.create(job)
        background_tasks.add_task(process_job, job_id, input_path, store, media, ai)
        return job

    @app.post("/api/jobs/{job_id}/retry", response_model=Job, status_code=202)
    def retry_job(job_id: str, background_tasks: BackgroundTasks) -> Job:
        job = store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        if job.status != JobStatus.failed:
            raise HTTPException(status_code=409, detail="只有失败的任务可以重新处理")
        source_files = sorted(store.job_dir(job_id).glob("source.*"))
        if not source_files:
            raise HTTPException(status_code=410, detail="原始文件已不存在，请重新上传")

        for filename in ("transcript.txt", "minutes.md"):
            (store.job_dir(job_id) / filename).unlink(missing_ok=True)
        retried = store.update(
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
        )
        background_tasks.add_task(process_job, job_id, source_files[0], store, media, ai)
        return retried

    @app.post("/api/jobs/{job_id}/review", response_model=Job, status_code=202)
    def start_review(job_id: str, background_tasks: BackgroundTasks) -> Job:
        job = store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        if job.status != JobStatus.completed or not job.transcript:
            raise HTTPException(status_code=409, detail="会议完成转写后才能进行智能校对")
        if job.review_status in {ReviewStatus.processing, ReviewStatus.applying}:
            raise HTTPException(status_code=409, detail="智能校对正在处理中")
        source_files = sorted(store.job_dir(job_id).glob("source.*"))
        if not source_files:
            raise HTTPException(status_code=410, detail="原始文件已不存在，无法校对")

        started = store.update(
            job_id,
            review_status=ReviewStatus.processing,
            review_stage="准备智能校对",
            review_progress=0,
            review_items=[],
            review_manual_corrections=[],
            review_error=None,
        )
        background_tasks.add_task(
            review_job,
            job_id,
            source_files[0],
            store,
            media,
            ai,
            ocr,
        )
        return started

    @app.get(
        "/api/jobs/{job_id}/review/search",
        response_model=list[ManualReviewMatch],
    )
    def search_review(
        job_id: str,
        term: Annotated[str, Query(min_length=1, max_length=100)],
    ) -> list[ManualReviewMatch]:
        job = store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        if job.review_status not in {ReviewStatus.ready, ReviewStatus.completed}:
            raise HTTPException(status_code=409, detail="请先运行智能校对以生成词级时间轴")
        cleaned_term = term.strip()
        if not cleaned_term:
            raise HTTPException(status_code=422, detail="请输入要查找的原词")
        try:
            return search_review_term(job_id, cleaned_term, store)
        except (OSError, ValueError):
            raise HTTPException(
                status_code=409,
                detail="词级时间轴不可用，请重新运行智能校对",
            ) from None

    @app.post("/api/jobs/{job_id}/review/apply", response_model=Job, status_code=202)
    def apply_review(
        job_id: str,
        submission: ReviewSubmission,
        background_tasks: BackgroundTasks,
    ) -> Job:
        job = store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        if job.review_status not in {ReviewStatus.ready, ReviewStatus.completed}:
            raise HTTPException(status_code=409, detail="当前没有可应用的校对结果")
        known_ids = {item.id for item in job.review_items}
        if any(correction.item_id not in known_ids for correction in submission.corrections):
            raise HTTPException(status_code=422, detail="校对项不存在或已过期")

        started = store.update(
            job_id,
            review_status=ReviewStatus.applying,
            review_stage="准备应用修正",
            review_progress=0,
            review_error=None,
        )
        background_tasks.add_task(
            apply_review_corrections,
            job_id,
            submission.corrections,
            submission.manual_corrections,
            store,
            ai,
        )
        return started

    def artifact(job_id: str, filename: str, media_type: str) -> FileResponse:
        if not store.get(job_id):
            raise HTTPException(status_code=404, detail="任务不存在")
        path = store.job_dir(job_id) / filename
        if not path.is_file():
            raise HTTPException(status_code=404, detail="文件尚未生成")
        return FileResponse(path, media_type=media_type, filename=filename)

    @app.get("/api/jobs/{job_id}/audio", response_class=FileResponse)
    def download_audio(job_id: str) -> FileResponse:
        return artifact(job_id, "compressed.mp3", "audio/mpeg")

    @app.get("/api/jobs/{job_id}/transcript", response_class=FileResponse)
    def download_transcript(job_id: str) -> FileResponse:
        return artifact(job_id, "transcript.txt", "text/plain; charset=utf-8")

    @app.get("/api/jobs/{job_id}/minutes", response_class=FileResponse)
    def download_minutes(job_id: str) -> FileResponse:
        return artifact(job_id, "minutes.md", "text/markdown; charset=utf-8")

    @app.get("/api/jobs/{job_id}/review/{item_id}/audio", response_class=FileResponse)
    def review_audio(job_id: str, item_id: str) -> FileResponse:
        job = store.get(job_id)
        if not job or item_id not in {item.id for item in job.review_items}:
            raise HTTPException(status_code=404, detail="校对片段不存在")
        path = store.job_dir(job_id) / "review" / "clips" / f"{item_id}.mp3"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="原声片段尚未生成")
        return FileResponse(path, media_type="audio/mpeg", filename=f"{item_id}.mp3")

    @app.get(
        "/api/jobs/{job_id}/review/{item_id}/frame/{frame_index}",
        response_class=FileResponse,
    )
    def review_frame(job_id: str, item_id: str, frame_index: int) -> FileResponse:
        job = store.get(job_id)
        item = (
            next((item for item in job.review_items if item.id == item_id), None)
            if job
            else None
        )
        if not item or frame_index < 0 or frame_index >= item.frame_count:
            raise HTTPException(status_code=404, detail="校对画面不存在")
        path = store.job_dir(job_id) / "review" / "frames" / f"{item_id}_{frame_index}.jpg"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="校对画面尚未生成")
        return FileResponse(path, media_type="image/jpeg", filename=f"{item_id}.jpg")

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
