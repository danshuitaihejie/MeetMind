from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from app.models import ChatNote, ChatNoteExchange, ChatSource

NOTES_ADAPTER = TypeAdapter(list[ChatNote])


class ChatNoteStore:
    """Persist annotated phrases and their follow-up explanations locally."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._notes: dict[str, ChatNote] = {}
        if path.is_file():
            try:
                notes = NOTES_ADAPTER.validate_json(path.read_bytes())
                self._notes = {note.id: note for note in notes}
            except (OSError, ValueError):
                pass

    def _persist(self) -> None:
        temporary = self.path.with_suffix(".tmp")
        payload = NOTES_ADAPTER.dump_json(list(self._notes.values()), indent=2)
        temporary.write_bytes(payload)
        temporary.replace(self.path)

    def list(self) -> list[ChatNote]:
        with self._lock:
            return [
                note.model_copy(deep=True)
                for note in sorted(
                    self._notes.values(), key=lambda item: item.updated_at, reverse=True,
                )
            ]

    def get(self, note_id: str) -> ChatNote | None:
        with self._lock:
            note = self._notes.get(note_id)
            return note.model_copy(deep=True) if note else None

    def create(self, note: ChatNote) -> ChatNote:
        with self._lock:
            self._notes[note.id] = note.model_copy(deep=True)
            self._persist()
            return note.model_copy(deep=True)

    def add_exchange(
        self,
        note_id: str,
        exchange: ChatNoteExchange,
        sources: list[ChatSource],
    ) -> ChatNote:
        with self._lock:
            note = self._notes[note_id]
            note.exchanges.append(exchange)
            note.sources = sources
            note.updated_at = datetime.now(UTC)
            self._persist()
            return note.model_copy(deep=True)

    def delete(self, note_id: str) -> bool:
        with self._lock:
            if note_id not in self._notes:
                return False
            del self._notes[note_id]
            self._persist()
            return True
