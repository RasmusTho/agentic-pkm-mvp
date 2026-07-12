from __future__ import annotations

from types import SimpleNamespace

import inspect

import pytest

from app.api.routes import ask
from tests.voice.conftest import ask_state, voice_request, voice_upload


def _patch_success(monkeypatch: pytest.MonkeyPatch, transcript: str) -> None:
    monkeypatch.setattr(ask, "transcribe_voice_audio", lambda _, **kwargs: {"text": transcript, "language": "en"})
    monkeypatch.setattr(ask, "run_ask_graph", lambda *_, **__: ask_state())
    monkeypatch.setattr(ask, "get_ask_settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(ask, "load_tts_config", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(ask, "build_tts_plan", lambda **_: {"audio_url": "/tts.wav"})
    monkeypatch.setattr(ask, "synthesize_tts", lambda **_: {"ok": False})


@pytest.mark.anyio
async def test_voice_turn_writes_no_vault_note(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_success(monkeypatch, "What is in my vault?")
    result = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    source = inspect.getsource(ask.ask_voice)
    assert result.answer == "Grounded answer"
    assert "write_ops" not in source
    assert "governed_write" not in source


@pytest.mark.anyio
async def test_capture_intent_is_surfaced_not_written(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_success(monkeypatch, "Remember this idea")
    result = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    assert result.reason == "capture_intent_surfaced"
    assert "capture" in result.answer.casefold()


@pytest.mark.anyio
async def test_retrieval_question_that_mentions_capture_wording_reaches_ask(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_success(monkeypatch, "Do you remember what I wrote about X?")
    result = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    assert result.answer == "Grounded answer"
    assert result.reason != "capture_intent_surfaced"
