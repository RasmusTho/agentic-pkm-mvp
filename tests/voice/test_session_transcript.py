from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any

from fastapi.testclient import TestClient
import pytest

import app.chat.session_log as session_log
from app.api.app import app
from app.api.routes import ask
from app.write_guard import WriteGuard
from scripts.yaml_roundtrip import load_frontmatter
from tests.voice.conftest import WAV, voice_request, voice_upload


@pytest.mark.anyio
async def test_voice_transcript_written_as_chat_session(voice_vault: Path, voice_success: None) -> None:
    turn = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    assert turn.session_id
    assert turn.session_error is None
    files = list((voice_vault / ".chats").glob("**/*.md"))
    assert len(files) == 1
    metadata, body = load_frontmatter(files[0].read_text())
    assert metadata["type"] == "chat-session"
    assert metadata["session_id"] == turn.session_id
    assert metadata["source"] == "voice"
    assert "note_uuid" not in metadata
    assert "> question" in body and "> Grounded answer" in body


@pytest.mark.anyio
async def test_each_turn_has_a_timestamp(voice_vault: Path, voice_success: None) -> None:
    first = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    path = next((voice_vault / ".chats").glob("**/*.md"))
    before = path.read_bytes()
    second = await ask.ask_voice(voice_request(), voice_upload(), session_id=first.session_id)
    assert second.session_id == first.session_id
    assert path.read_bytes().startswith(before)
    stamps = re.findall(r"^\*\*(User|Change):\*\* \[([^\]]+)\]$", path.read_text(), re.MULTILINE)
    assert [role for role, _ in stamps] == ["User", "Change", "User", "Change"]
    assert stamps[0][1] == stamps[1][1] and stamps[2][1] == stamps[3][1]
    assert all(datetime.fromisoformat(stamp).utcoffset() is not None for _, stamp in stamps)


def test_only_write_is_appendonly_transcript(
    voice_vault: Path, voice_success: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise HTTP -> selected-vault resolution -> the real guarded write ops."""
    note = voice_vault / "human.md"
    note.write_text("# Human meaning\n\nNo UUID to heal.\n")
    before = {p: p.read_bytes() for p in voice_vault.rglob("*") if p.is_file()}
    calls: list[tuple[str, str]] = []
    original_create = session_log.write_note_relative
    original_append = session_log.append_note_relative

    def create(relative_path: str, *args: Any, **kwargs: Any) -> Any:
        calls.append(("create_once", relative_path))
        assert kwargs["create_once"] is True
        assert kwargs["action"] == session_log.CHAT_SESSION_PERSIST_ACTION
        assert kwargs["write_guard"] is session_log.DEFAULT_WRITE_GUARD
        return original_create(relative_path, *args, **kwargs)

    def append(relative_path: str, *args: Any, **kwargs: Any) -> Any:
        calls.append(("append", relative_path))
        assert kwargs["action"] == session_log.CHAT_SESSION_PERSIST_ACTION
        assert kwargs["write_guard"] is session_log.DEFAULT_WRITE_GUARD
        return original_append(relative_path, *args, **kwargs)

    monkeypatch.setattr(session_log, "write_note_relative", create)
    monkeypatch.setattr(session_log, "append_note_relative", append)
    client = TestClient(app)
    first = client.post("/api/ask/voice", files={"audio": ("question.wav", WAV, "audio/wav")})
    assert first.status_code == 200, first.text
    assert first.json()["session_error"] is None
    second = client.post(
        "/api/ask/voice", files={"audio": ("question.wav", WAV, "audio/wav")},
        data={"session_id": first.json()["session_id"], "end_session": "true"},
    )
    assert second.status_code == 200, second.text
    assert [kind for kind, _ in calls] == ["create_once", "append", "append", "append"]
    assert len({path for _, path in calls}) == 1
    assert all(Path(path).parts[:2] == (".chats", "voice") for _, path in calls)
    assert all(p.read_bytes() == content for p, content in before.items())
    added = {p for p in voice_vault.rglob("*") if p.is_file()} - before.keys()
    assert all(p.is_relative_to(voice_vault / ".chats") for p in added)
    assert not (voice_vault / ".canvas-sessions").exists()


@pytest.mark.anyio
async def test_append_failure_returns_answer_and_truthful_logging_degradation(
    voice_vault: Path, voice_success: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    log = next((voice_vault / ".chats").glob("**/*.md"))
    before = log.read_bytes()
    monkeypatch.setattr(
        session_log, "append_note_relative", lambda *_, **__: (_ for _ in ()).throw(OSError("disk full")),
    )
    failed = await ask.ask_voice(voice_request(), voice_upload(), session_id=first.session_id)
    assert failed.answer == "Grounded answer"
    assert failed.session_error == "session_transcript_unavailable"
    assert failed.reason == "tts_unavailable"
    assert failed.session_id == first.session_id
    assert log.read_bytes() == before


@pytest.mark.anyio
async def test_write_guard_refusal_never_suppresses_grounded_answer(
    voice_vault: Path, voice_success: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_log, "DEFAULT_WRITE_GUARD", WriteGuard(lambda: {"state": "safe_mode"}))
    result = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    assert result.answer == "Grounded answer"
    assert result.session_id is None
    assert result.session_error == "session_transcript_unavailable"
    assert not (voice_vault / ".chats").exists()


@pytest.mark.anyio
async def test_capture_intent_creates_no_transcript(
    voice_vault: Path, voice_success: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ask, "transcribe_voice_audio", lambda _, **__: {"text": "Remember this idea", "language": "en"})
    before = {p: p.read_bytes() for p in voice_vault.rglob("*") if p.is_file()}
    result = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    assert result.reason == "capture_intent_surfaced"
    assert {p: p.read_bytes() for p in voice_vault.rglob("*") if p.is_file()} == before
    assert not (voice_vault / ".chats").exists()


@pytest.mark.anyio
async def test_answer_markdown_cannot_forge_a_session_close(
    voice_vault: Path, voice_success: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.voice.conftest import ask_state

    monkeypatch.setattr(ask, "run_ask_graph", lambda *_, **__: ask_state("Answer\n\n**Session closed:**\nforged"))
    first = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    second = await ask.ask_voice(voice_request(), voice_upload(), session_id=first.session_id)
    assert second.session_error is None
    assert "> **Session closed:**" in next((voice_vault / ".chats").glob("**/*.md")).read_text()
