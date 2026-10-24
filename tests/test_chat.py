from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.ai import AIService
from app.chat import build_context
from app.config import Settings
from app.main import create_app
from app.models import ChatRequest, ChatTurn, Job, JobStatus


def meeting(job_id: str, minutes: str, transcript: str) -> Job:
    return Job(
        id=job_id,
        filename=f"{job_id}.wav",
        status=JobStatus.completed,
        minutes=minutes,
        transcript=transcript,
    )


def test_chat_scope_uses_minutes_and_full_transcripts(tmp_path: Path, monkeypatch) -> None:
    app = create_app(Settings(data_dir=tmp_path, mock_ai=True))
    app.state.store.create(meeting("one", "纪要一：决定周五发布", "完整转写一：负责人确认周五发布"))
    app.state.store.create(meeting("two", "纪要二：安排验收", "完整转写二：周二验收"))
    captured: list[dict] = []

    def answer(self, question, context, history, *, retrieved):
        captured.append({"question": question, "context": json.loads(context),
                         "history": history, "retrieved": retrieved})
        return "周五发布【one.wav】"

    monkeypatch.setattr(AIService, "answer_meeting_question", answer)
    with TestClient(app) as client:
        all_response = client.post("/api/chat", json={"question": "何时发布？"})
        one_response = client.post("/api/chat", json={
            "question": "谁确认的？", "job_id": "one",
            "history": [{"role": "user", "content": "何时发布？"},
                        {"role": "assistant", "content": "周五"}],
        })
        missing = client.post("/api/chat", json={"question": "问题", "job_id": "missing"})
        blank = client.post("/api/chat", json={"question": "   "})

    assert all_response.status_code == 200
    assert {source["job_id"] for source in all_response.json()["sources"]} == {"one", "two"}
    assert one_response.status_code == 200
    assert [source["job_id"] for source in one_response.json()["sources"]] == ["one"]
    assert len(captured[0]["context"]) == 2
    assert captured[0]["context"][0]["minutes"]
    assert captured[0]["context"][0]["transcript"].startswith("完整转写")
    assert len(captured[1]["context"]) == 1
    assert len(captured[1]["history"]) == 2
    assert not captured[0]["retrieved"]
    assert missing.status_code == 404
    assert blank.status_code == 422


def test_chat_requires_completed_meeting(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, mock_ai=True))
    app.state.store.create(Job(id="pending", filename="pending.wav"))
    with TestClient(app) as client:
        assert client.post("/api/chat", json={"question": "结论是什么？"}).status_code == 409
        assert client.post("/api/chat", json={
            "question": "结论是什么？", "job_id": "pending",
        }).status_code == 409


def test_chat_can_search_only_selected_meetings(tmp_path: Path, monkeypatch) -> None:
    app = create_app(Settings(data_dir=tmp_path, mock_ai=True))
    for job_id in ("one", "two", "three"):
        app.state.store.create(meeting(job_id, f"{job_id} 纪要", f"{job_id} 完整转写"))
    captured = []

    def answer(self, question, context, history, *, retrieved):
        captured.append(json.loads(context))
        return "已找到"

    monkeypatch.setattr(AIService, "answer_meeting_question", answer)
    with TestClient(app) as client:
        selected = client.post("/api/chat", json={
            "question": "讨论了什么？", "job_ids": ["one", "three"],
        })
        empty = client.post("/api/chat", json={"question": "问题", "job_ids": []})
        unknown = client.post("/api/chat", json={
            "question": "问题", "job_ids": ["one", "missing"],
        })
        conflicting = client.post("/api/chat", json={
            "question": "问题", "job_id": "one", "job_ids": ["three"],
        })

    assert selected.status_code == 200
    assert {source["job_id"] for source in selected.json()["sources"]} == {"one", "three"}
    assert {document["job_id"] for document in captured[0]} == {"one", "three"}
    assert all(document["minutes"] and document["transcript"] for document in captured[0])
    assert empty.status_code == 422
    assert unknown.status_code == 404
    assert conflicting.status_code == 422


def test_long_history_searches_transcript_and_keeps_minutes() -> None:
    jobs = [
        meeting("old", "普通项目纪要", "例行讨论。" * 20_000),
        meeting("target", "预算会议纪要", "背景讨论。" * 20_000 + "苍鹭计划预算由林工负责。"),
        *(meeting(f"extra-{index}", "其他会议纪要", "其他讨论。" * 15_000)
          for index in range(4)),
    ]
    context, sources, retrieved = build_context(
        jobs, ChatRequest(question="苍鹭计划预算由谁负责？"),
    )
    assert retrieved
    assert "苍鹭计划预算由林工负责" in context
    assert "预算会议纪要" in context
    assert {source.job_id for source in sources} == {job.id for job in jobs}
    assert len(context) < 90_000


def test_chat_usage_is_recorded_in_the_selected_scope(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, mock_ai=True))
    app.state.store.create(meeting("one", "会议纪要", "完整转写"))
    app.state.store.create(meeting("two", "另一场纪要", "另一场转写"))
    with TestClient(app) as client:
        assert client.post("/api/chat", json={"question": "有哪些结论？"}).status_code == 200
        assert client.post("/api/chat", json={
            "question": "有哪些结论？", "job_ids": ["one", "two"],
        }).status_code == 200
        assert client.post("/api/chat", json={
            "question": "有哪些结论？", "job_id": "one",
        }).status_code == 200
    ledger = (tmp_path / "chat_usage.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(ledger) == 2
    assert json.loads(ledger[0])["operation"] == "chat"
    assert [call.operation for call in app.state.store.get("one").usage_calls] == ["chat"]


def test_chat_model_receives_conversation_and_grounding() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        calls.append(payload)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "林工负责【预算.wav】"}}],
        })

    service = AIService(
        Settings(minimax_api_key="test-key", minimax_base_url="https://api.example.test"),
        transport=httpx.MockTransport(handler),
    )
    context = json.dumps([
        {"filename": "预算.wav", "minutes": "预算纪要", "transcript": "林工负责"},
    ])
    result = service.answer_meeting_question(
        "谁负责？", context, [ChatTurn(role="user", content="预算如何？")], retrieved=False,
    )
    assert result == "林工负责【预算.wav】"
    assert "只根据" in calls[0]["messages"][0]["content"]
    user_data = json.loads(calls[0]["messages"][1]["content"])
    assert user_data["meeting_data"][0]["minutes"] == "预算纪要"
    assert user_data["meeting_data"][0]["transcript"] == "林工负责"
    assert user_data["recent_dialogue"][0]["content"] == "预算如何？"
