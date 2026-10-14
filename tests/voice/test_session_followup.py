from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from app.api.routes import ask, vault_resolution
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager
from tests.voice.conftest import ask_state, voice_request, voice_upload


def _question(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr(ask, "transcribe_voice_audio", lambda _, **__: {"text": text, "language": "en"})


@pytest.mark.anyio
async def test_followup_resolves_against_in_session_context(
    voice_vault: Path, voice_success: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    questions: list[str] = []
    citation = {"id": "project-x", "payload": {"title": "Project X", "path": "notes/x.md"}}

    def grounded_fixture(question: str, **_: object) -> SimpleNamespace:
        questions.append(question)
        if "Prior Q&A from this voice session" in question:
            history = json.loads(question.split("source evidence):\n", 1)[1])
            assert history[0]["question"] == "What are the options for Project X?"
            assert history[0]["citations"][0]["uuid"] == "project-x"
            assert history[0]["answer"] == "First: defer. Second: pilot Project X."
            return SimpleNamespace(answer="The second option is to pilot Project X.", hits=[citation])
        if "second option" in question:
            return ask_state("Which project do you mean?")
        return SimpleNamespace(answer="First: defer. Second: pilot Project X.", hits=[citation])

    monkeypatch.setattr(ask, "run_ask_graph", grounded_fixture)
    _question(monkeypatch, "What are the options for Project X?")
    first = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    assert first.session_id
    assert first.session_error is None
    _question(monkeypatch, "And the second option?")
    followup = await ask.ask_voice(voice_request(), voice_upload(), session_id=first.session_id)
    cold = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    assert followup.answer == "The second option is to pilot Project X."
    assert cold.answer == "Which project do you mean?"
    assert followup.session_id == first.session_id != cold.session_id
    assert followup.transcript == "And the second option?"
    assert questions[-1] == "And the second option?"
    assert len(list((voice_vault / ".chats").glob("**/*.md"))) == 2
    assert any('"uuid": "project-x"' in path.read_text() for path in (voice_vault / ".chats").glob("**/*.md"))


@pytest.mark.anyio
async def test_context_does_not_leak_across_sessions(
    voice_vault: Path, voice_success: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(ask, "run_ask_graph", lambda question, **_: seen.append(question) or ask_state())
    _question(monkeypatch, "Private Project X options")
    first = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    _question(monkeypatch, "And the second option?")
    second = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    assert first.session_id != second.session_id
    assert seen[1] == "And the second option?"
    assert "Private Project X" not in seen[1]
    # Simulate process loss: neither pointers nor Q&A are restored from disk.
    durable = {path: path.read_bytes() for path in (voice_vault / ".chats").glob("**/*.md")}
    ask._VOICE_SESSIONS.clear()
    with pytest.raises(HTTPException) as lost:
        await ask.ask_voice(voice_request(), voice_upload(), session_id=first.session_id)
    assert lost.value.status_code == 409
    assert lost.value.detail["error"] == "voice_session_context_lost"
    assert len(seen) == 2
    assert all(path.read_bytes() == content for path, content in durable.items())
    assert not (voice_vault / ".canvas-sessions").exists()


@pytest.mark.anyio
async def test_session_cannot_borrow_context_after_scope_or_vault_change(
    voice_vault: Path, voice_success: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = await ask.ask_voice(voice_request(), voice_upload(), session_id=None, scope="work")
    with pytest.raises(HTTPException) as changed_scope:
        await ask.ask_voice(voice_request(), voice_upload(), session_id=first.session_id, scope="home")
    assert changed_scope.value.status_code == 409
    manager = VaultManager(app_local_store=AppLocalSettingsStore(voice_vault.parent / "other-local.md"))
    manager.initialize_vault(voice_vault.parent / "other-vault", vault_name="other", remember=False)
    monkeypatch.setattr(vault_resolution, "get_vault_manager", lambda: manager)
    with pytest.raises(HTTPException) as changed_vault:
        await ask.ask_voice(voice_request(), voice_upload(), session_id=first.session_id, scope="work")
    assert changed_vault.value.status_code == 409


@pytest.mark.anyio
async def test_ambient_scope_change_refuses_retained_context(
    voice_vault: Path, voice_success: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASK_DOMAIN_SCOPE", "work")
    first = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    monkeypatch.setenv("ASK_DOMAIN_SCOPE", "home")
    with pytest.raises(HTTPException) as changed:
        await ask.ask_voice(voice_request(), voice_upload(), session_id=first.session_id)
    assert changed.value.detail["error"] == "voice_session_context_lost"


@pytest.mark.anyio
async def test_closed_session_cannot_resume(
    voice_vault: Path, voice_success: None,
) -> None:
    first = await ask.ask_voice(voice_request(), voice_upload(), session_id=None, end_session=True)
    log = next((voice_vault / ".chats").glob("**/*.md"))
    assert "**Session closed:**" in log.read_text()
    with pytest.raises(HTTPException) as closed:
        await ask.ask_voice(voice_request(), voice_upload(), session_id=first.session_id)
    assert closed.value.detail["error"] == "voice_session_context_lost"
