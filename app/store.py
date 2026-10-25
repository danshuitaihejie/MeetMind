from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.corrections import CorrectionMemory, CorrectionRecord
from app.models import AIUsageCall, Job, MinutesVersion, ReviewStatus


class JobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._load()
        self.corrections = CorrectionMemory(root.parent / "corrections.sqlite3")
        self._import_confirmed_corrections()

    def _import_confirmed_corrections(self) -> None:
        """Recover confirmations from jobs created before shared correction memory."""
        records: list[CorrectionRecord] = []
        for job in self._jobs.values():
            if job.review_status != ReviewStatus.completed and not job.review_applied:
                continue
            for item in job.review_items:
                if item.correction_term is not None and item.correction_term != item.original_term:
                    records.append(CorrectionRecord(
                        job_id=job.id,
                        segment_index=item.segment_index,
                        term_start=(
                            item.term_start if item.term_start is not None
                            else max(0, item.context_text.find(item.original_term))
                        ),
                        original_term=item.original_term,
                        replacement=item.correction_term,
                        context_text=item.context_text,
                        source=(
                            "asr_conflict" if item.requires_confirmation
                            else "agent" if item.source == "agent" else "suggested"
                        ),
                        created_at=job.updated_at.isoformat(),
                    ))
            contexts: dict[int, str] = {}
            if job.review_manual_corrections:
                try:
                    payload = json.loads(
                        (self.root / job.id / "review" / "segments.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    if isinstance(payload, list):
                        contexts = {
                            item["index"]: item["text"] for item in payload
                            if isinstance(item, dict) and "index" in item and "text" in item
                        }
                except (OSError, ValueError):
                    pass
            for correction in job.review_manual_corrections:
                records.append(CorrectionRecord(
                    job_id=job.id,
                    segment_index=correction.segment_index,
                    term_start=correction.term_start,
                    original_term=correction.original_term,
                    replacement=correction.replacement,
                    context_text=contexts.get(correction.segment_index, job.transcript or ""),
                    source="manual" if correction.learn_globally else "asr_conflict",
                    created_at=job.updated_at.isoformat(),
                ))
        self.corrections.remember(records)

    def _load(self) -> None:
        for path in self.root.glob("*/job.json"):
            self._load_one(path)

    def _load_one(self, path: Path) -> None:
        try:
            job = Job.model_validate_json(path.read_text(encoding="utf-8"))
            self._jobs[job.id] = job
        except (OSError, ValueError):
            pass

    def job_dir(self, job_id: str) -> Path:
        path = self.root / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _persist(self, job: Job) -> None:
        path = self.job_dir(job.id) / "job.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)

    def create(self, job: Job) -> Job:
        with self._lock:
            self._jobs[job.id] = job
            self._persist(job)
            return job.model_copy(deep=True)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            if Path(job_id).name == job_id and job_id not in {".", ".."}:
                self._load_one(self.root / job_id / "job.json")
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def list(self) -> list[Job]:
        with self._lock:
            self._load()
            jobs = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
            return [job.model_copy(deep=True) for job in jobs]

    def update(self, job_id: str, **values: Any) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in values.items():
                setattr(job, key, value)
            job.updated_at = datetime.now(UTC)
            self._persist(job)
            return job.model_copy(deep=True)

    def record_usage(self, job_id: str, call: AIUsageCall) -> None:
        """Persist each response immediately, including failed/repeated attempts."""
        with self._lock:
            job = self._jobs[job_id]
            job.usage_calls.append(call.model_copy(deep=True))
            job.updated_at = datetime.now(UTC)
            self._persist(job)

    def record_chat_usage(self, call: AIUsageCall) -> None:
        """Keep cross-meeting calls separate from any individual meeting's usage."""
        with self._lock:
            with (self.root.parent / "chat_usage.jsonl").open("a", encoding="utf-8") as ledger:
                ledger.write(call.model_dump_json() + "\n")

    def save_minutes(self, job_id: str, content: str, *, regenerated: bool = False) -> Job:
        """Publish the latest minutes and retain every successful generation."""
        with self._lock:
            job = self._jobs[job_id]
            path = self.job_dir(job_id) / "minutes.md"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(path)
            job.minutes_versions.append(MinutesVersion(
                content=content,
                source="regenerated" if regenerated or job.minutes_versions else "initial",
            ))
            job.minutes = content
            job.updated_at = datetime.now(UTC)
            self._persist(job)
            return job.model_copy(deep=True)
