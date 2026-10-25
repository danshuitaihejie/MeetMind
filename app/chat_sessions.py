from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from app.models import ChatSession, ChatSessionMessage

SESSIONS_ADAPTER = TypeAdapter(list[ChatSession])


class ChatSessionStore:
    """Persist meeting conversations, including their selected meeting scope."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._sessions: dict[str, ChatSession] = {}
        if path.is_file():
            saved = json.loads(path.read_bytes())
            for item in saved:
                had_title_origin = "title_is_manual" in item
                if "title_is_manual" not in item and item.get("messages"):
                    first_question = next(
                        (message["content"] for message in item["messages"]
                         if message.get("role") == "user"),
                        "",
                    )
                    item["title_is_manual"] = item.get("title") not in (
                        "新对话", first_question[:40],
                    )
                if "title_generated_by_ai" not in item:
                    item["title_generated_by_ai"] = bool(
                        had_title_origin
                        and not item["title_is_manual"]
                        and item.get("messages")
                    )
            sessions = SESSIONS_ADAPTER.validate_python(saved)
            self._sessions = {session.id: session for session in sessions}

    def _persist(self) -> None:
        temporary = self.path.with_suffix(".tmp")
        payload = SESSIONS_ADAPTER.dump_json(list(self._sessions.values()), indent=2)
        temporary.write_bytes(payload)
        temporary.replace(self.path)

    def list(self) -> list[ChatSession]:
        with self._lock:
            return [
                session.model_copy(deep=True)
                for session in sorted(
                    self._sessions.values(), key=lambda item: item.updated_at, reverse=True,
                )
            ]

    def get(self, session_id: str) -> ChatSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            return session.model_copy(deep=True) if session else None

    def create(self, scope_job_ids: list[str]) -> ChatSession:
        with self._lock:
            session = ChatSession(scope_job_ids=scope_job_ids)
            self._sessions[session.id] = session
            self._persist()
            return session.model_copy(deep=True)

    def append_exchange(
        self,
        session_id: str,
        expected_message_count: int,
        question: ChatSessionMessage,
        answer: ChatSessionMessage,
        title: str,
        title_generated_by_ai: bool,
    ) -> ChatSession:
        with self._lock:
            session = self._sessions[session_id]
            if len(session.messages) != expected_message_count:
                raise ValueError("对话已更新，请重试")
            session.messages.extend([question, answer])
            if not session.title_is_manual:
                session.title = title[:80] or question.content[:40]
                session.title_generated_by_ai = title_generated_by_ai
            session.updated_at = datetime.now(UTC)
            self._persist()
            return session.model_copy(deep=True)

    def rename(self, session_id: str, title: str) -> ChatSession:
        with self._lock:
            session = self._sessions[session_id]
            session.title = title
            session.title_is_manual = True
            session.title_generated_by_ai = False
            session.updated_at = datetime.now(UTC)
            self._persist()
            return session.model_copy(deep=True)

    def delete(self, session_id: str) -> bool:
        with self._lock:
            if session_id not in self._sessions:
                return False
            del self._sessions[session_id]
            self._persist()
            return True
