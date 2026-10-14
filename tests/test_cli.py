from __future__ import annotations

import json
import shutil
import wave
from pathlib import Path

import pytest

from app.cli import main
from app.models import Job, JobStatus
from app.store import JobStore


def _sample_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 16000)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is not installed")
def test_cli_process_query_review_and_apply(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("MEETMIND_MOCK_AI", "1")
    sample = tmp_path / "meeting.wav"
    _sample_wav(sample)
    data_dir = tmp_path / "runtime"
    observer = JobStore(data_dir / "jobs")
    prefix = ["--data-dir", str(data_dir)]

    assert main([*prefix, "process", str(sample), "--no-trim-silence"]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["status"] == "completed"
    assert Path(created["artifacts"]["minutes"]).is_file()
    assert "MeetMind" in created["minutes"]
    job_id = created["id"]
    assert observer.get(job_id).status == "completed"
    assert observer.list()[0].id == job_id

    assert main([*prefix, "show", job_id]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["id"] == job_id
    assert main([*prefix, "list"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == job_id

    assert main([*prefix, "review", job_id]) == 0
    reviewed = json.loads(capsys.readouterr().out)
    assert reviewed["review_status"] == "ready"
    item = reviewed["review_items"][0]
    assert Path(item["evidence"]["audio"]).is_file()
    assert reviewed["pending_review_count"] == 1

    assert main([*prefix, "search", job_id, "流程"]) == 0
    uncertain = json.loads(capsys.readouterr().out)[0]
    assert main([
        *prefix, "flag", job_id, "流程",
        "--segment-index", str(uncertain["segment_index"]),
        "--term-start", str(uncertain["term_start"]),
        "--reason", "Agent 无法确认是否应改为步骤",
        "--suggested", "步骤",
    ]) == 0
    flagged = json.loads(capsys.readouterr().out)
    assert flagged["pending_review_count"] == 2
    agent_item = next(entry for entry in flagged["review_items"] if entry["source"] == "agent")
    assert Path(agent_item["evidence"]["audio"]).is_file()

    assert main([*prefix, "search", job_id, "第一版"]) == 0
    match = json.loads(capsys.readouterr().out)[0]
    assert Path(match["audio"]).is_file()
    submission = tmp_path / "corrections.json"
    submission.write_text(json.dumps({
        "corrections": [{"item_id": item["id"], "replacement": "MeetMind"}],
        "manual_corrections": [{
            "segment_index": match["segment_index"],
            "term_start": match["term_start"],
            "original_term": match["original_term"],
            "replacement": "首版",
        }],
    }), encoding="utf-8")
    assert main([*prefix, "apply", job_id, "--input", str(submission)]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["review_status"] == "ready"
    assert applied["pending_review_count"] == 1
    assert "首版流程" in applied["transcript"]
    (data_dir / "corrections.sqlite3").unlink()
    assert main([*prefix, "pending", job_id]) == 0
    pending = json.loads(capsys.readouterr().out)
    assert pending["pending_review_count"] == 1
    assert [entry["id"] for entry in pending["items"]] == [agent_item["id"]]
    assert len(JobStore(data_dir / "jobs").corrections.records()) == 2

    # A second incremental submission keeps earlier AI and manual edits.
    submission.write_text(json.dumps({
        "corrections": [{"item_id": agent_item["id"], "replacement": "流程"}],
        "manual_corrections": [],
    }), encoding="utf-8")
    assert main([*prefix, "apply", job_id, "--input", str(submission)]) == 0
    completed = json.loads(capsys.readouterr().out)
    assert completed["review_status"] == "completed"
    assert completed["pending_review_count"] == 0
    assert "MeetMind 首版流程" in completed["transcript"]
    assert not any(
        record.original_term == "流程"
        for record in JobStore(data_dir / "jobs").corrections.records()
    )


def test_cli_error_is_json_and_nonzero(tmp_path: Path, capsys) -> None:
    assert main(["--data-dir", str(tmp_path), "show", "missing"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"error": "任务不存在", "code": "cli_error"}


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is not installed")
def test_cli_retries_failed_job(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("MEETMIND_MOCK_AI", "1")
    store = JobStore(tmp_path / "jobs")
    store.create(Job(
        id="failed-job", filename="meeting.wav", status=JobStatus.failed, trim_silence=False,
    ))
    _sample_wav(store.job_dir("failed-job") / "source.wav")

    assert main(["--data-dir", str(tmp_path), "retry", "failed-job"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "completed"
    assert Path(result["artifacts"]["minutes"]).is_file()
