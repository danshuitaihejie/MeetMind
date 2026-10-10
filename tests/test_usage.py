from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from app.ai import AIService, MiniMaxAPIError
from app.config import Settings
from app.models import AIUsageCall, Job, JobStatus
from app.store import JobStore


def make_service(
    transport: httpx.BaseTransport,
    callback,
    *,
    sleeper=lambda _: None,
) -> AIService:
    service = AIService(
        Settings(minimax_api_key="test-key", minimax_base_url="https://api.example.test"),
        transport=transport,
        sleeper=sleeper,
    )
    return service.with_usage_recorder(callback)


def text_payload(
    *,
    prompt: int = 100,
    completion: int = 20,
    total: int = 120,
    cached: int | None = None,
    content: str = "会议纪要",
) -> dict:
    usage = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }
    if cached is not None:
        usage["prompt_tokens_details"] = {"cached_tokens": cached}
    return {
        "choices": [{"message": {"content": content}}],
        "usage": usage,
    }


def usage_call(**overrides) -> AIUsageCall:
    values = {
        "operation": "summary",
        "kind": "text",
        "model": "MiniMax-M2.7",
        "attempt": 1,
        "status": "success",
        "http_status": 200,
        "request_id": None,
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
        "cached_input_tokens": 10,
        "audio_duration_seconds": None,
    }
    values.update(overrides)
    return AIUsageCall(**values)


def job(job_id: str, **fields) -> Job:
    return Job(
        id=job_id,
        filename=f"{job_id}.mp3",
        status=JobStatus.completed,
        **fields,
    )


def test_text_response_records_exact_usage_and_cached_tokens_once() -> None:
    records: list[AIUsageCall] = []
    responses = iter([
        text_payload(prompt=140, completion=30, total=170, cached=55),
        text_payload(prompt=80, completion=10, total=90, cached=25),
    ])
    service = make_service(
        httpx.MockTransport(lambda _: httpx.Response(200, json=next(responses))),
        records.append,
    )

    service.summarize("第一场会议")
    service.with_usage_recorder(
        records.append,
        operation_override="summary_regeneration",
    ).summarize("重新生成")

    assert [(record.operation, record.kind) for record in records] == [
        ("summary", "text"),
        ("summary_regeneration", "text"),
    ]
    assert [
        (
            record.input_tokens,
            record.output_tokens,
            record.total_tokens,
            record.cached_input_tokens,
        )
        for record in records
    ] == [(140, 30, 170, 55), (80, 10, 90, 25)]


def test_clone_has_independent_recorder_and_preserves_transport_and_sleeper() -> None:
    first: list[AIUsageCall] = []
    second: list[AIUsageCall] = []
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=text_payload()))
    sleeps: list[float] = []
    base = AIService(
        Settings(minimax_api_key="test-key", minimax_base_url="https://api.example.test"),
        transport=transport,
        sleeper=sleeps.append,
    )
    clone = base.with_usage_recorder(first.append)
    clone.with_usage_recorder(second.append, operation_override="review_transcription").summarize(
        "校对"
    )
    clone.summarize("纪要")

    assert len(first) == 1
    assert len(second) == 1
    assert first[0].operation == "summary"
    assert second[0].operation == "review_transcription"
    assert clone.transport is transport
    assert clone.sleeper is sleeps.append or clone.sleeper == sleeps.append


def test_missing_text_usage_is_unknown_not_zero_and_mock_is_not_missing(
    tmp_path: Path,
) -> None:
    records: list[AIUsageCall] = []

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "完成"}}]})

    make_service(httpx.MockTransport(handler), records.append).summarize("转写")
    store = JobStore(tmp_path / "jobs")
    store.create(job("no-usage"))
    store.record_usage("no-usage", records[0])
    store.record_usage(
        "no-usage",
        usage_call(
            operation="summary",
            status="mock",
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            cached_input_tokens=None,
        ),
    )

    summary = store.get("no-usage").usage_summary
    assert summary.call_count == 2
    assert summary.text_call_count == 1
    assert summary.mock_call_count == 1
    assert summary.input_tokens is None
    assert summary.output_tokens is None
    assert summary.total_tokens is None
    assert summary.cached_input_tokens is None
    assert summary.missing_text_usage_calls == 1


def test_asr_duration_is_recorded_without_fabricating_tokens(tmp_path: Path) -> None:
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"fake-audio")
    records: list[AIUsageCall] = []

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "转写完成", "duration": 19.75})

    make_service(httpx.MockTransport(handler), records.append).transcribe(audio)
    store = JobStore(tmp_path / "jobs")
    store.create(job("asr"))
    store.record_usage("asr", records[0])
    store.record_usage(
        "asr",
        usage_call(
            operation="transcription",
            kind="asr",
            model="asr-1.0",
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            cached_input_tokens=None,
            audio_duration_seconds=None,
        ),
    )

    summary = store.get("asr").usage_summary
    assert summary.asr_call_count == 2
    assert summary.asr_duration_seconds == pytest.approx(19.75)
    assert summary.missing_asr_duration_calls == 1
    assert summary.input_tokens is None
    assert summary.total_tokens is None


def test_http_500_retry_records_each_attempt_and_success(tmp_path: Path) -> None:
    records: list[AIUsageCall] = []
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(500, json={"error": "temporary", "usage": {"prompt_tokens": 3}})
        return httpx.Response(200, json=text_payload(prompt=9, completion=4, total=13))

    service = make_service(httpx.MockTransport(handler), records.append)
    assert service.summarize("会议") == "会议纪要"
    assert attempts == 2
    assert [record.attempt for record in records] == [1, 2]
    assert [record.status for record in records] == ["http_error", "success"]
    assert [record.http_status for record in records] == [500, 200]
    assert records[0].input_tokens == 3
    assert records[1].total_tokens == 13

    store = JobStore(tmp_path / "jobs")
    store.create(job("retry"))
    for record in records:
        store.record_usage("retry", record)
    assert store.get("retry").usage_summary.call_count == 2
    assert store.get("retry").usage_summary.total_tokens == 13
    assert store.get("retry").usage_summary.failed_call_count == 1


def test_usage_is_recorded_when_valid_json_has_no_usable_content() -> None:
    records: list[AIUsageCall] = []

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"usage": {"prompt_tokens": 21, "completion_tokens": 2,
            "total_tokens": 23}, "choices": []})

    service = make_service(httpx.MockTransport(handler), records.append)
    with pytest.raises(MiniMaxAPIError, match="可用内容"):
        service.summarize("会议")

    assert len(records) == 1
    assert records[0].status == "success"
    assert records[0].input_tokens == 21
    assert records[0].output_tokens == 2
    assert records[0].total_tokens == 23


def test_non_json_response_is_recorded_as_invalid_response() -> None:
    records: list[AIUsageCall] = []

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    service = make_service(httpx.MockTransport(handler), records.append)
    with pytest.raises(MiniMaxAPIError, match="无法解析"):
        service.summarize("会议")

    assert len(records) == 1
    assert records[0].status == "invalid_response"
    assert records[0].input_tokens is None


def test_network_timeout_attempts_are_recorded_with_unknown_usage() -> None:
    records: list[AIUsageCall] = []
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("read timed out")

    service = make_service(httpx.MockTransport(handler), records.append)
    with pytest.raises(MiniMaxAPIError, match="超时"):
        service.summarize("会议")

    assert attempts == 3
    assert len(records) == 3
    assert [record.attempt for record in records] == [1, 2, 3]
    assert all(record.status == "network_error" for record in records)
    assert all(record.http_status is None for record in records)
    assert all(record.input_tokens is None and record.total_tokens is None for record in records)


def test_store_is_thread_safe_persists_per_job_and_loads_legacy_jobs(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    store = JobStore(root)
    store.create(job("one"))
    store.create(job("two"))
    store.create(job("old"))
    # Simulate a job.json written before usage_calls was introduced.
    old_path = root / "old" / "job.json"
    old_payload = json.loads(old_path.read_text(encoding="utf-8"))
    old_payload.pop("usage_calls", None)
    old_path.write_text(json.dumps(old_payload), encoding="utf-8")

    def add_usage(index: int) -> None:
        target = "one" if index % 2 == 0 else "two"
        store.record_usage(
            target,
            usage_call(
                operation="summary",
                input_tokens=1,
                output_tokens=2,
                total_tokens=3,
                cached_input_tokens=1,
                request_id=f"req-{index}",
            ),
        )

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(add_usage, range(100)))

    restarted = JobStore(root)
    one = restarted.get("one")
    two = restarted.get("two")
    old = restarted.get("old")
    assert one.usage_summary.call_count == 50
    assert two.usage_summary.call_count == 50
    assert one.usage_summary.total_tokens == 150
    assert two.usage_summary.total_tokens == 150
    assert len({call.request_id for call in one.usage_calls}) == 50
    assert len({call.request_id for call in two.usage_calls}) == 50
    assert old.usage_calls == []
    assert old.usage_summary.call_count == 0
