from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.api.routes import ask
from tests.voice.conftest import ask_state, voice_request, voice_upload


@pytest.mark.anyio
async def test_stt_unavailable_is_explicit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ask, "transcribe_voice_audio", lambda _, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(HTTPException) as error:
        await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    assert error.value.detail["error"] == "stt_unavailable"


@pytest.mark.anyio
async def test_ask_down_returns_transcript_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ask, "transcribe_voice_audio", lambda _, **kwargs: {"text": "heard words", "language": "en"})
    monkeypatch.setattr(ask, "get_ask_settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(ask, "run_ask_graph", lambda *_, **__: (_ for _ in ()).throw(RuntimeError("ASK down")))
    result = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    assert isinstance(result, JSONResponse)
    assert result.status_code == 503
    assert b"heard words" in result.body
    assert b"ASK down" not in result.body


@pytest.mark.anyio
async def test_tts_down_returns_text_answer_with_degrade_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ask, "transcribe_voice_audio", lambda _, **kwargs: {"text": "question", "language": "en"})
    monkeypatch.setattr(ask, "get_ask_settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(ask, "run_ask_graph", lambda *_, **__: ask_state())
    monkeypatch.setattr(ask, "load_tts_config", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(ask, "build_tts_plan", lambda **_: {"audio_url": "/tts.wav"})
    monkeypatch.setattr(ask, "synthesize_tts", lambda **_: {"ok": False, "state": "unavailable"})
    result = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    assert result.answer == "Grounded answer"
    assert result.degraded is True
    assert result.reason == "tts_unavailable"
    assert result.audio_url is None
