from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.corrections import CorrectionMemory, CorrectionRecord
from app.models import (
    AIUsageCall,
    Job,
    MinutesTextCorrection,
    MinutesVersion,
    ReviewStatus,
)


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

    def save_minutes(
        self, job_id: str, content: str, *, regenerated: bool = False,
        source: Literal["manual"] | None = None,
    ) -> Job:
        """Publish the latest minutes and retain every successful generation."""
        with self._lock:
            job = self._jobs[job_id]
            path = self.job_dir(job_id) / "minutes.md"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(path)
            job.minutes_versions.append(MinutesVersion(
                content=content,
                source=source or (
                    "regenerated" if regenerated or job.minutes_versions else "initial"
                ),
            ))
            job.minutes = content
            job.updated_at = datetime.now(UTC)
            self._persist(job)
            return job.model_copy(deep=True)

    def delete_minutes_version(
        self, job_id: str, version: int, latest_version: int,
    ) -> Job:
        """Remove one snapshot and publish the last remaining version, if any."""
        with self._lock:
            job = self._jobs[job_id]
            if job.review_status == ReviewStatus.applying:
                raise ValueError("转写修正正在生成纪要，请稍后重试")
            if len(job.minutes_versions) != latest_version:
                raise ValueError("纪要版本已有变化，请刷新后重试")
            if version < 1 or version > len(job.minutes_versions):
                raise ValueError("所选纪要版本不存在")
            job.minutes_versions.pop(version - 1)
            job.minutes = job.minutes_versions[-1].content if job.minutes_versions else None
            path = self.job_dir(job_id) / "minutes.md"
            if job.minutes is None:
                path.unlink(missing_ok=True)
            else:
                temporary = path.with_suffix(".tmp")
                temporary.write_text(job.minutes, encoding="utf-8")
                temporary.replace(path)
            job.updated_at = datetime.now(UTC)
            self._persist(job)
            return job.model_copy(deep=True)

    def correct_minutes(
        self, job_id: str, source_version: int, latest_version: int,
        corrections: list[MinutesTextCorrection],
    ) -> Job:
        """Apply exact edits to a selected snapshot, then publish a new version."""
        with self._lock:
            job = self._jobs[job_id]
            if job.review_status == ReviewStatus.applying:
                raise ValueError("转写修正正在生成纪要，请稍后重试")
            if len(job.minutes_versions) != latest_version:
                raise ValueError("纪要已有新版本，请刷新后重新核对修正")
            if source_version > latest_version:
                raise ValueError("所选纪要版本不存在")
            content = job.minutes_versions[source_version - 1].content
            ordered = sorted(corrections, key=lambda item: item.start)
            previous_end = 0
            for correction in ordered:
                end = correction.start + len(correction.original)
                if correction.start < previous_end:
                    raise ValueError("纪要修正位置重叠，请重新选择")
                if content[correction.start:end] != correction.original:
                    raise ValueError("纪要修正位置已失效，请重新查找")
                if correction.original == correction.replacement:
                    raise ValueError("修正内容与原文相同")
                previous_end = end
            for correction in reversed(ordered):
                end = correction.start + len(correction.original)
                content = content[:correction.start] + correction.replacement + content[end:]
            return self.save_minutes(job_id, content, source="manual")
