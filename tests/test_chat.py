from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.ai import AIService
from app.chat import build_context
from app.chat_sessions import ChatSessionStore
from app.config import Settings
from app.main import create_app
from app.models import (
    ChatNoteExchange,
    ChatPronunciation,
    ChatRequest,
    ChatSession,
    ChatSessionMessage,
    ChatTurn,
    Job,
    JobStatus,
)


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


def test_chat_title_uses_first_question_and_recent_dialogue() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.read()))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "“预算与发布日期”"}}],
        })

    service = AIService(
        Settings(minimax_api_key="test-key", minimax_base_url="https://api.example.test"),
        transport=httpx.MockTransport(handler),
    )
    title = service.generate_chat_title([
        ChatSessionMessage(role="user", content="谁负责预算？"),
        ChatSessionMessage(role="assistant", content="林工负责"),
        ChatSessionMessage(role="user", content="发布日期呢？"),
    ])
    assert title == "预算与发布日期"
    data = json.loads(calls[0]["messages"][1]["content"])
    assert data["first_question"] == "谁负责预算？"
    assert data["recent_dialogue"][-1]["content"] == "发布日期呢？"


def test_existing_manual_title_stays_manual_after_upgrade(tmp_path: Path) -> None:
    session = ChatSession(
        scope_job_ids=["one"], title="我保存的标题",
        messages=[ChatSessionMessage(role="user", content="首次提问是什么？")],
    )
    saved = session.model_dump(mode="json")
    del saved["title_is_manual"]
    path = tmp_path / "chat_sessions.json"
    path.write_text(json.dumps([saved], ensure_ascii=False), encoding="utf-8")
    restored = ChatSessionStore(path).get(session.id)
    assert restored is not None
    assert restored.title_is_manual
    assert not restored.title_generated_by_ai
    assert restored.title == "我保存的标题"


def test_ai_title_badge_tracks_actual_title_source(tmp_path: Path, monkeypatch) -> None:
    app = create_app(Settings(data_dir=tmp_path, minimax_api_key="test-key"))
    app.state.store.create(meeting("one", "纪要", "完整转写"))
    monkeypatch.setattr(AIService, "answer_meeting_question", lambda *args, **kwargs: "会议回答")
    monkeypatch.setattr(AIService, "generate_chat_title", lambda *args: "项目发布日期")
    with TestClient(app) as client:
        session_id = client.post("/api/chat/sessions", json={
            "scope_job_ids": ["one"],
        }).json()["id"]
        created = client.post(f"/api/chat/sessions/{session_id}/messages", json={
            "question": "什么时候发布？",
        }).json()
        assert created["title"] == "项目发布日期"
        assert created["title_generated_by_ai"]
        renamed = client.patch(f"/api/chat/sessions/{session_id}", json={
            "title": "我的标题",
        }).json()
        assert renamed["title_is_manual"]
        assert not renamed["title_generated_by_ai"]


def test_chat_note_persists_and_supports_follow_up(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, mock_ai=True))
    app.state.store.create(meeting("one", "# 预算会", "苍鹭计划预算由林工负责"))
    app.state.store.create(meeting("two", "# 发布会", "周五发布"))
    payload = {
        "phrase": "苍鹭计划",
        "source_excerpt": "苍鹭计划预算由林工负责",
        "scope_job_ids": ["one", "two"],
        "message_id": "message-1",
        "selection_start": 0,
        "selection_end": 4,
    }
    with TestClient(app) as client:
        created = client.post("/api/chat/notes", json=payload)
        assert created.status_code == 201
        note = created.json()
        assert note["phrase"] == "苍鹭计划"
        assert len(note["exchanges"]) == 1
        assert {source["job_id"] for source in note["sources"]} == {"one", "two"}
        followed = client.post(
            f"/api/chat/notes/{note['id']}/ask", json={"question": "谁负责预算？"},
        )
        assert followed.status_code == 200
        assert [turn["question"] for turn in followed.json()["exchanges"]] == [
            "释义", "谁负责预算？",
        ]
        assert len(client.get("/api/chat/notes").json()) == 1

    restarted = create_app(Settings(data_dir=tmp_path, mock_ai=True))
    with TestClient(restarted) as client:
        saved = client.get("/api/chat/notes").json()
    assert saved[0]["id"] == note["id"]
    assert len(saved[0]["exchanges"]) == 2
    assert len((tmp_path / "chat_usage.jsonl").read_text().splitlines()) == 2


def test_chat_note_validates_scope_and_selection(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, mock_ai=True))
    app.state.store.create(meeting("one", "纪要", "转写"))
    app.state.store.create(Job(id="pending", filename="pending.wav"))
    payload = {
        "phrase": "术语", "source_excerpt": "这段包含术语", "scope_job_ids": ["one"],
        "message_id": "message-1", "selection_start": 4, "selection_end": 6,
    }
    with TestClient(app) as client:
        assert client.post("/api/chat/notes", json={
            **payload, "selection_end": 4,
        }).status_code == 422
        assert client.post("/api/chat/notes", json={
            **payload, "selection_end": 7,
        }).status_code == 422
        assert client.post("/api/chat/notes", json={
            **payload, "source_excerpt": "这里没有选中的字",
        }).status_code == 422
        assert client.post("/api/chat/notes", json={
            **payload, "scope_job_ids": ["one", "missing"],
        }).status_code == 404
        assert client.post("/api/chat/notes", json={
            **payload, "scope_job_ids": ["one", "pending"],
        }).status_code == 409
        assert client.post("/api/chat/notes/missing/ask", json={
            "question": "继续解释",
        }).status_code == 404


def test_note_model_receives_phrase_and_follow_up_context() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.read()))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({
                "answer": "这是上下文释义【预算.wav】",
                "ipa": "/ˈbʌdʒɪt/", "language": "en-US",
            })}}],
        })

    service = AIService(
        Settings(minimax_api_key="test-key", minimax_base_url="https://api.example.test"),
        transport=httpx.MockTransport(handler),
    )
    context = json.dumps([
        {"filename": "预算.wav", "minutes": "预算纪要", "transcript": "林工负责"},
    ])
    answer, pronunciation = service.explain_meeting_phrase(
        "budget", "budget 由林工负责", "具体是谁负责？", context,
        [ChatNoteExchange(question="释义", answer="此前的解释")], retrieved=False,
    )
    assert "上下文释义" in answer
    assert pronunciation is not None
    assert pronunciation.ipa == "/ˈbʌdʒɪt/"
    data = json.loads(calls[0]["messages"][1]["content"])
    assert data["marked_phrase"] == "budget"
    assert data["meeting_data"][0]["transcript"] == "林工负责"
    assert data["earlier_exchanges"][0]["answer"] == "此前的解释"
    instructions = calls[0]["messages"][0]["content"]
    assert "音标" in instructions
    assert "词性" in instructions
    assert "例句" in instructions


def test_saved_chat_sessions_restore_messages_and_link_annotations(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, mock_ai=True))
    app.state.store.create(meeting("one", "预算会议", "budget 由林工负责"))
    app.state.store.create(meeting("two", "发布会议", "周五发布"))
    with TestClient(app) as client:
        created = client.post("/api/chat/sessions", json={"scope_job_ids": ["one", "two"]})
        assert created.status_code == 201
        session_id = created.json()["id"]
        answered = client.post(f"/api/chat/sessions/{session_id}/messages", json={
            "question": "budget 是谁负责？",
        })
        assert answered.status_code == 200
        session = answered.json()
        assert [message["role"] for message in session["messages"]] == ["user", "assistant"]
        assert session["title"] == "budget 是谁负责？"
        assert {source["job_id"] for source in session["messages"][1]["sources"]} == {
            "one", "two",
        }
        continued = client.post(f"/api/chat/sessions/{session_id}/messages", json={
            "question": "发布日期是什么时候？",
        })
        assert continued.status_code == 200
        assert continued.json()["title"] == "发布日期是什么时候？"
        assert continued.json()["messages"][0]["content"] == "budget 是谁负责？"
        message = session["messages"][0]
        note = client.post("/api/chat/notes", json={
            "phrase": "budget", "source_excerpt": "budget 是谁负责？",
            "scope_job_ids": ["one", "two"], "session_id": session_id,
            "message_id": message["id"], "selection_start": 0, "selection_end": 6,
        })
        assert note.status_code == 201
        assert note.json()["session_id"] == session_id
        renamed = client.patch(f"/api/chat/sessions/{session_id}", json={
            "title": "项目预算",
        })
        assert renamed.json()["title"] == "项目预算"
        assert renamed.json()["title_is_manual"]
        after_rename = client.post(f"/api/chat/sessions/{session_id}/messages", json={
            "question": "还需要谁确认？",
        })
        assert after_rename.json()["title"] == "项目预算"

    restored = create_app(Settings(data_dir=tmp_path, mock_ai=True))
    with TestClient(restored) as client:
        sessions = client.get("/api/chat/sessions").json()
        assert len(sessions) == 1
        assert sessions[0]["title"] == "项目预算"
        assert sessions[0]["messages"][0]["id"] == message["id"]
        assert client.get("/api/chat/notes").json()[0]["session_id"] == session_id
        assert client.delete(f"/api/chat/sessions/{session_id}").status_code == 204
        assert client.get("/api/chat/sessions").json() == []
        assert len(client.get("/api/chat/notes").json()) == 1
        assert client.delete(f"/api/chat/notes/{note.json()['id']}").status_code == 204
        assert client.get("/api/chat/notes").json() == []


def test_chat_session_and_annotation_validate_scope_and_source(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, mock_ai=True))
    app.state.store.create(meeting("one", "预算会议", "完整转写"))
    with TestClient(app) as client:
        assert client.post("/api/chat/sessions", json={
            "scope_job_ids": ["missing"],
        }).status_code == 404
        session_id = client.post("/api/chat/sessions", json={
            "scope_job_ids": ["one"],
        }).json()["id"]
        assert client.post(f"/api/chat/sessions/{session_id}/messages", json={
            "question": "  ",
        }).status_code == 422
        assert client.get("/api/chat/sessions/missing").status_code == 404
        assert client.patch(f"/api/chat/sessions/{session_id}", json={
            "title": "  ",
        }).status_code == 422
        answered = client.post(f"/api/chat/sessions/{session_id}/messages", json={
            "question": "术语是什么意思？",
        }).json()
        message_id = answered["messages"][0]["id"]
        note = {
            "phrase": "术语", "source_excerpt": "术语是什么意思？",
            "scope_job_ids": ["one"], "session_id": session_id,
            "message_id": message_id, "selection_start": 0, "selection_end": 2,
        }
        assert client.post("/api/chat/notes", json={
            **note, "phrase": "意思", "selection_start": 2, "selection_end": 4,
        }).status_code == 422
        assert client.post("/api/chat/notes", json={
            **note, "source_excerpt": "不存在术语的文字",
        }).status_code == 422
        assert client.post("/api/chat/notes", json={
            **note, "scope_job_ids": ["missing"],
        }).status_code == 404


def test_english_note_saves_phonetic_pronunciation(tmp_path: Path, monkeypatch) -> None:
    app = create_app(Settings(data_dir=tmp_path, mock_ai=True))
    app.state.store.create(meeting("one", "预算会议", "The budget is approved."))

    def explain(self, phrase, source_excerpt, question, context, exchanges, *, retrieved):
        return "名词：预算。例句：The budget is approved. 预算已获批准。", ChatPronunciation(
            ipa="/ˈbʌdʒɪt/", language="en-US",
        )

    monkeypatch.setattr(AIService, "explain_meeting_phrase", explain)
    with TestClient(app) as client:
        response = client.post("/api/chat/notes", json={
            "phrase": "budget", "source_excerpt": "The budget is approved.",
            "scope_job_ids": ["one"], "message_id": "example",
            "selection_start": 4, "selection_end": 10,
        })
        assert response.status_code == 201
        assert response.json()["pronunciation"] == {
            "ipa": "/ˈbʌdʒɪt/", "language": "en-US",
        }
    restored = create_app(Settings(data_dir=tmp_path, mock_ai=True))
    with TestClient(restored) as client:
        assert client.get("/api/chat/notes").json()[0]["pronunciation"]["ipa"] == "/ˈbʌdʒɪt/"
