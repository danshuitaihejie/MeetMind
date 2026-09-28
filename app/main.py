from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.ai import AIService
from app.config import Settings
from app.media import MediaProcessor
from app.models import HealthResponse, Job, JobStatus
from app.pipeline import process_job
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

    app = FastAPI(title="MeetMind", version="0.1.0")
    app.state.settings = app_settings
    app.state.store = store
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
        )
        background_tasks.add_task(process_job, job_id, source_files[0], store, media, ai)
        return retried

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

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
