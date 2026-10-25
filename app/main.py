from __future__ import annotations

import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.ai import AIConfigurationError, AIService, MiniMaxAPIError
from app.alignment import ensure_original_audio, ensure_segments, locate_text, source_path
from app.chat import add_source_passages, available_jobs, build_context
from app.chat_notes import ChatNoteStore
from app.chat_sessions import ChatSessionStore
from app.config import Settings
from app.media import MediaProcessor
from app.models import (
    ChatLocateRequest,
    ChatNote,
    ChatNoteCreate,
    ChatNoteExchange,
    ChatNoteQuestion,
    ChatPassage,
    ChatPronunciation,
    ChatRequest,
    ChatResponse,
    ChatSession,
    ChatSessionCreate,
    ChatSessionMessage,
    ChatSessionQuestion,
    ChatSessionUpdate,
    ChatSource,
    ChatTurn,
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
from app.validation import ALLOWED_EXTENSIONS, MAX_CONTEXT_CHARS, SPEED_OPTIONS

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    store = JobStore(app_settings.data_dir / "jobs")
    note_store = ChatNoteStore(app_settings.data_dir / "chat_notes.json")
    session_store = ChatSessionStore(app_settings.data_dir / "chat_sessions.json")
    media = MediaProcessor()
    ai = AIService(app_settings)
    ocr = OCRService()

    app = FastAPI(title="MeetMind", version="0.1.0")
    app.state.settings = app_settings
    app.state.store = store
    app.state.note_store = note_store
    app.state.session_store = session_store
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

    def resolve_chat_jobs(selected_ids: list[str] | None) -> list[Job]:
        if selected_ids is not None and not selected_ids:
            raise HTTPException(status_code=422, detail="请至少选择一场会议")
        selected_set = set(selected_ids) if selected_ids is not None else None
        all_jobs = store.list()
        if selected_set and not selected_set.issubset({job.id for job in all_jobs}):
            raise HTTPException(status_code=404, detail="会议不存在")
        jobs = available_jobs(all_jobs, selected_set)
        if not jobs:
            raise HTTPException(status_code=409, detail="所选范围内还没有已完成的会议纪要和转写")
        if selected_set and len(jobs) != len(selected_set):
            raise HTTPException(status_code=409, detail="所选会议中有尚未完成纪要和转写的会议")
        return jobs

    def explain_note(
        phrase: str,
        source_excerpt: str,
        question: str,
        jobs: list[Job],
        exchanges: list[ChatNoteExchange],
    ) -> tuple[str, list[ChatSource], ChatPronunciation | None]:
        search = ChatRequest(question=f"{phrase} {source_excerpt} {question}"[:2000])
        context, sources, retrieved = build_context(jobs, search)
        note_ai = (
            ai.with_usage_recorder(lambda call: store.record_usage(jobs[0].id, call))
            if len(jobs) == 1 else ai.with_usage_recorder(store.record_chat_usage)
        )
        try:
            answer, pronunciation = note_ai.explain_meeting_phrase(
                phrase, source_excerpt, question, context, exchanges, retrieved=retrieved,
            )
        except AIConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except MiniMaxAPIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        sources = add_source_passages(
            jobs, sources, f"{phrase} {source_excerpt} {question} {answer}", store.root,
        )
        return answer, sources, pronunciation

    def answer_chat(question: str, jobs: list[Job], history: list[ChatTurn]) -> ChatResponse:
        request = ChatRequest(question=question, history=history)
        context, sources, retrieved = build_context(jobs, request)
        chat_ai = (
            ai.with_usage_recorder(lambda call: store.record_usage(jobs[0].id, call))
            if len(jobs) == 1 else ai.with_usage_recorder(store.record_chat_usage)
        )
        try:
            answer = chat_ai.answer_meeting_question(
                question, context, history, retrieved=retrieved,
            )
        except AIConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except MiniMaxAPIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        sources = add_source_passages(jobs, sources, f"{question} {answer}", store.root)
        return ChatResponse(answer=answer, sources=sources, retrieved=retrieved)

    def restore_session_passages(session: ChatSession) -> ChatSession:
        jobs = [job for job_id in session.scope_job_ids if (job := store.get(job_id))]
        for index, message in enumerate(session.messages):
            if message.role != "assistant" or not message.sources:
                continue
            if any(source.passages for source in message.sources):
                continue
            question = session.messages[index - 1].content if index else ""
            message.sources = add_source_passages(
                jobs, message.sources, f"{question} {message.content}", store.root,
            )
        return session

    def restore_note_passages(note: ChatNote) -> ChatNote:
        jobs = [job for job_id in note.scope_job_ids if (job := store.get(job_id))]
        for exchange in note.exchanges:
            if exchange.sources and any(source.passages for source in exchange.sources):
                continue
            base = exchange.sources or note.sources
            exchange.sources = add_source_passages(
                jobs, base,
                f"{note.phrase} {note.source_excerpt} {exchange.question} {exchange.answer}",
                store.root,
            )
        return note

    @app.post("/api/chat", response_model=ChatResponse)
    def ask_meetings(request: ChatRequest) -> ChatResponse:
        question = request.question.strip()
        if not question:
            raise HTTPException(status_code=422, detail="请输入问题")
        if request.job_ids is not None and request.job_id is not None:
            raise HTTPException(status_code=422, detail="不能同时指定 job_id 和 job_ids")
        selected_ids = (
            request.job_ids if request.job_ids is not None
            else [request.job_id] if request.job_id is not None else None
        )
        jobs = resolve_chat_jobs(selected_ids)
        return answer_chat(question, jobs, request.history)

    @app.get("/api/chat/sessions", response_model=list[ChatSession])
    def list_chat_sessions() -> list[ChatSession]:
        return [restore_session_passages(session) for session in session_store.list()]

    @app.post("/api/chat/sessions", response_model=ChatSession, status_code=201)
    def create_chat_session(request: ChatSessionCreate) -> ChatSession:
        ids = list(dict.fromkeys(request.scope_job_ids))
        resolve_chat_jobs(ids)
        return session_store.create(ids)

    @app.get("/api/chat/sessions/{session_id}", response_model=ChatSession)
    def get_chat_session(session_id: str) -> ChatSession:
        session = session_store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="对话不存在")
        return restore_session_passages(session)

    @app.post("/api/chat/sessions/{session_id}/messages", response_model=ChatSession)
    def ask_chat_session(session_id: str, request: ChatSessionQuestion) -> ChatSession:
        session = session_store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="对话不存在")
        question = request.question.strip()
        if not question:
            raise HTTPException(status_code=422, detail="请输入问题")
        jobs = resolve_chat_jobs(session.scope_job_ids)
        history = [
            ChatTurn(role=message.role, content=message.content[:4000])
            for message in session.messages[-10:]
        ]
        result = answer_chat(question, jobs, history)
        user_message = ChatSessionMessage(role="user", content=question)
        assistant_message = ChatSessionMessage(
            role="assistant", content=result.answer,
            sources=result.sources, retrieved=result.retrieved,
        )
        title = session.title if session.messages else question[:40]
        title_generated_by_ai = session.title_generated_by_ai
        if not session.title_is_manual:
            title_ai = (
                ai.with_usage_recorder(lambda call: store.record_usage(jobs[0].id, call))
                if len(jobs) == 1 else ai.with_usage_recorder(store.record_chat_usage)
            )
            try:
                title = title_ai.generate_chat_title(
                    [*session.messages, user_message, assistant_message],
                )
                title_generated_by_ai = not app_settings.mock_ai
            except (AIConfigurationError, MiniMaxAPIError):
                pass
        try:
            return session_store.append_exchange(
                session_id,
                len(session.messages),
                user_message,
                assistant_message,
                title,
                title_generated_by_ai,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="对话不存在") from exc

    @app.patch("/api/chat/sessions/{session_id}", response_model=ChatSession)
    def rename_chat_session(session_id: str, request: ChatSessionUpdate) -> ChatSession:
        title = request.title.strip()
        if not title:
            raise HTTPException(status_code=422, detail="请输入对话名称")
        try:
            return session_store.rename(session_id, title)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="对话不存在") from exc

    @app.delete("/api/chat/sessions/{session_id}", status_code=204)
    def delete_chat_session(session_id: str) -> None:
        if not session_store.delete(session_id):
            raise HTTPException(status_code=404, detail="对话不存在")

    @app.get("/api/chat/notes", response_model=list[ChatNote])
    def list_chat_notes() -> list[ChatNote]:
        return [restore_note_passages(note) for note in note_store.list()]

    @app.post("/api/chat/notes", response_model=ChatNote, status_code=201)
    def create_chat_note(request: ChatNoteCreate) -> ChatNote:
        phrase = request.phrase.strip()
        excerpt = request.source_excerpt.strip()
        if not phrase or not excerpt:
            raise HTTPException(status_code=422, detail="请选择要标注的词语")
        scope_job_ids = list(dict.fromkeys(request.scope_job_ids))
        jobs = resolve_chat_jobs(scope_job_ids)
        question = "请解释这个词或短语的通常含义，以及在所选会议中的具体含义。"
        if request.session_id is not None:
            session = session_store.get(request.session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="对话不存在")
            if set(session.scope_job_ids) != set(scope_job_ids):
                raise HTTPException(status_code=422, detail="标注范围与对话不一致")
            message = next(
                (item for item in session.messages if item.id == request.message_id), None,
            )
            if message is None or message.content[
                request.selection_start:request.selection_end
            ] != phrase or excerpt not in message.content:
                raise HTTPException(status_code=422, detail="标注内容与对话不一致")
        answer, sources, pronunciation = explain_note(phrase, excerpt, question, jobs, [])
        note = ChatNote(
            phrase=phrase,
            source_excerpt=excerpt,
            scope_job_ids=scope_job_ids,
            message_id=request.message_id,
            session_id=request.session_id,
            selection_start=request.selection_start,
            selection_end=request.selection_end,
            exchanges=[ChatNoteExchange(question="释义", answer=answer, sources=sources)],
            sources=sources,
            pronunciation=pronunciation,
        )
        return note_store.create(note)

    @app.post("/api/chat/notes/{note_id}/ask", response_model=ChatNote)
    def ask_chat_note(note_id: str, request: ChatNoteQuestion) -> ChatNote:
        note = note_store.get(note_id)
        if not note:
            raise HTTPException(status_code=404, detail="标注不存在")
        question = request.question.strip()
        if not question:
            raise HTTPException(status_code=422, detail="请输入追问")
        if len(note.exchanges) >= 20:
            raise HTTPException(status_code=409, detail="这条标注的追问已达到上限")
        jobs = resolve_chat_jobs(note.scope_job_ids)
        answer, sources, _ = explain_note(
            note.phrase, note.source_excerpt, question, jobs, note.exchanges,
        )
        try:
            return note_store.add_exchange(
                note_id,
                ChatNoteExchange(question=question, answer=answer, sources=sources),
                sources,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="标注不存在") from exc

    @app.delete("/api/chat/notes/{note_id}", status_code=204)
    def delete_chat_note(note_id: str) -> None:
        if not note_store.delete(note_id):
            raise HTTPException(status_code=404, detail="标注不存在")

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
        if len(context) > MAX_CONTEXT_CHARS:
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
            review_applied=False,
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

    @app.get("/api/jobs/{job_id}/source", response_class=FileResponse)
    def original_media(job_id: str) -> FileResponse:
        job = store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        suffix = Path(job.filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=404, detail="原始文件不存在")
        path = source_path(store, job)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="原始文件不存在")
        media_type = mimetypes.guess_type(job.filename)[0] or "application/octet-stream"
        return FileResponse(
            path, media_type=media_type, filename=job.filename,
            content_disposition_type="inline",
        )

    @app.post("/api/jobs/{job_id}/locate", response_model=ChatPassage)
    def locate_original_media(job_id: str, request: ChatLocateRequest) -> ChatPassage:
        job = store.get(job_id)
        if not job or job.status != JobStatus.completed:
            raise HTTPException(status_code=404, detail="会议不存在")
        if not source_path(store, job).is_file():
            raise HTTPException(status_code=404, detail="原始音视频文件不存在")
        alignment_ai = ai.with_usage_recorder(
            lambda call: store.record_usage(job_id, call),
            operation_override="source_alignment",
        )
        try:
            segments = ensure_segments(store, job, media, alignment_ai)
        except AIConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (MiniMaxAPIError, RuntimeError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        result = locate_text(request.text, segments)
        if result is None:
            raise HTTPException(status_code=404, detail="未能在原媒体中准确定位这段话")
        return result

    @app.get("/api/jobs/{job_id}/source-audio", response_class=FileResponse)
    def original_media_audio(job_id: str) -> FileResponse:
        job = store.get(job_id)
        if not job or not source_path(store, job).is_file():
            raise HTTPException(status_code=404, detail="原始音视频文件不存在")
        try:
            path = ensure_original_audio(store, job, media)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return FileResponse(path, media_type="audio/mpeg", filename="original_speed.mp3",
                            content_disposition_type="inline")

    @app.get("/api/jobs/{job_id}/transcript", response_class=FileResponse)
    def download_transcript(job_id: str) -> FileResponse:
        return artifact(job_id, "transcript.txt", "text/plain; charset=utf-8")

    @app.get("/api/jobs/{job_id}/minutes", response_class=FileResponse)
    def download_minutes(job_id: str) -> FileResponse:
        return artifact(job_id, "minutes.md", "text/markdown; charset=utf-8")

    @app.get("/api/jobs/{job_id}/minutes/{version}")
    def download_minutes_version(job_id: str, version: int) -> Response:
        job = store.get(job_id)
        if not job or version < 1 or version > len(job.minutes_versions):
            raise HTTPException(status_code=404, detail="纪要版本不存在")
        return Response(
            content=job.minutes_versions[version - 1].content,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="minutes-v{version}.md"',
            },
        )

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

    uvicorn.run("app.main:app", host="127.0.0.1", port=18473, reload=True)
