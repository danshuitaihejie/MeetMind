from __future__ import annotations

import json
import math
import re
from collections import Counter

from app.models import ChatRequest, ChatSource, Job, JobStatus

MAX_CONTEXT_CHARS = 90_000
CHUNK_CHARS = 1800
CHUNK_OVERLAP = 160
MAX_MATCHES = 16


def available_jobs(jobs: list[Job], job_ids: set[str] | None) -> list[Job]:
    completed = [
        job for job in jobs
        if job.status == JobStatus.completed and job.minutes and job.transcript
    ]
    if job_ids is None:
        return completed
    return [job for job in completed if job.id in job_ids]


def _terms(text: str) -> set[str]:
    lowered = text.casefold()
    words = set(re.findall(r"[a-z0-9][a-z0-9_.-]{1,}", lowered))
    for group in re.findall(r"[\u3400-\u9fff]+", lowered):
        words.update(group[index : index + 2] for index in range(len(group) - 1))
        if len(group) == 1:
            words.add(group)
    return words


def _chunks(text: str) -> list[str]:
    if len(text) <= CHUNK_CHARS:
        return [text]
    chunks = []
    step = CHUNK_CHARS - CHUNK_OVERLAP
    for start in range(0, len(text), step):
        chunk = text[start : start + CHUNK_CHARS]
        if chunk:
            chunks.append(chunk)
    return chunks


def _document(job: Job, transcript: str) -> dict[str, str]:
    return {
        "job_id": job.id,
        "filename": job.filename,
        "created_at": job.created_at.isoformat(),
        "minutes": job.minutes or "",
        "transcript": transcript,
    }


def build_context(jobs: list[Job], request: ChatRequest) -> tuple[str, list[ChatSource], bool]:
    """Search the entire transcript corpus; send full documents whenever they fit."""
    full_documents = [_document(job, job.transcript or "") for job in jobs]
    full_context = json.dumps(full_documents, ensure_ascii=False)
    if len(full_context) <= MAX_CONTEXT_CHARS:
        sources = [
            ChatSource(job_id=job.id, filename=job.filename, created_at=job.created_at)
            for job in jobs
        ]
        return full_context, sources, False

    query = request.question + " " + " ".join(
        turn.content for turn in request.history[-4:] if turn.role == "user"
    )
    query_terms = _terms(query)
    passages: list[tuple[Job, int, str, set[str]]] = []
    for job in jobs:
        # Minutes and every transcript character participate in retrieval.
        for index, chunk in enumerate(_chunks(job.minutes or "")):
            passages.append((job, -index - 1, chunk, _terms(chunk)))
        for index, chunk in enumerate(_chunks(job.transcript or "")):
            passages.append((job, index, chunk, _terms(chunk)))

    document_frequency = Counter(
        term for _, _, _, terms in passages for term in terms if term in query_terms
    )
    count = len(passages)

    def score(passage: tuple[Job, int, str, set[str]]) -> float:
        _, index, _, terms = passage
        overlap = terms & query_terms
        relevance = sum(
            1 + math.log((count + 1) / (document_frequency[term] + 1))
            for term in overlap
        )
        return relevance * (1.15 if index < 0 else 1)

    ranked = sorted(passages, key=score, reverse=True)
    best_ids = list(dict.fromkeys(job.id for job, _, _, _ in ranked))[:MAX_MATCHES]
    # Reserve one passage per meeting so comparisons are not crowded out by
    # many high-scoring chunks from a single long transcript.
    selected = [
        next(passage for passage in ranked if passage[0].id == job_id and passage[1] >= 0)
        for job_id in best_ids
    ]
    selected_keys = {(job.id, index) for job, index, _, _ in selected}
    for passage in ranked:
        key = (passage[0].id, passage[1])
        if passage[0].id in best_ids and key not in selected_keys:
            selected.append(passage)
            selected_keys.add(key)
        if len(selected) >= MAX_MATCHES:
            break
    selected_ids = {job.id for job, _, _, _ in selected}
    selected_jobs = [job for job in jobs if job.id in selected_ids]
    minutes_limit = min(
        8_000,
        max(1_000, (MAX_CONTEXT_CHARS - MAX_MATCHES * CHUNK_CHARS - 4_000) // len(selected_jobs)),
    )
    documents = []
    for job in selected_jobs:
        matches = [
            {"section": "minutes" if index < 0 else "transcript", "part": abs(index) + 1,
             "text": chunk}
            for item_job, index, chunk, _ in selected if item_job.id == job.id
        ]
        documents.append({
            "job_id": job.id,
            "filename": job.filename,
            "created_at": job.created_at.isoformat(),
            "minutes": (job.minutes or "")[:minutes_limit],
            "matched_passages": matches,
        })
    context = json.dumps(documents, ensure_ascii=False)
    sources = [
        ChatSource(job_id=job.id, filename=job.filename, created_at=job.created_at)
        for job in selected_jobs
    ]
    return context, sources, True
