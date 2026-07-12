from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.routes import ask
from tests.voice.conftest import ask_state, voice_request, voice_upload


@pytest.mark.anyio
async def test_audio_question_returns_grounded_spoken_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ask, "transcribe_voice_audio", lambda _, **kwargs: {"text": "What is in my vault?", "language": "en"})
    monkeypatch.setattr(ask, "run_ask_graph", lambda *_, **__: ask_state())
    monkeypatch.setattr(ask, "get_ask_settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(ask, "load_tts_config", lambda: SimpleNamespace(enabled=True))
    plan = {"audio_url": "/api/companion/tts/audio/key.wav", "voice_id": "bf_isabella"}
    monkeypatch.setattr(ask, "build_tts_plan", lambda **_: plan)
    monkeypatch.setattr(ask, "synthesize_tts", lambda **_: {"ok": True, "audio_url": plan["audio_url"]})

    result = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)

    assert result.transcript == "What is in my vault?"
    assert result.answer == "Grounded answer"
    assert result.audio_url == plan["audio_url"]


@pytest.mark.anyio
async def test_voice_ask_warms_retrieval_before_running_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    warmed = False

    def warm() -> None:
        nonlocal warmed
        warmed = True

    monkeypatch.setattr(ask, "_HYBRID_WARMED", False)
    monkeypatch.setattr(ask, "_ensure_hybrid_store_loaded", warm)
    monkeypatch.setattr(ask, "transcribe_voice_audio", lambda _, **kwargs: {"text": "What is in my vault?", "language": "en"})
    monkeypatch.setattr(ask, "run_ask_graph", lambda *_, **__: ask_state())
    monkeypatch.setattr(ask, "get_ask_settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(ask, "load_tts_config", lambda: SimpleNamespace(enabled=False))
    monkeypatch.setattr(ask, "build_tts_plan", lambda **_: {"audio_url": "/tts.wav"})

    result = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)

    assert warmed is True
    assert result.answer == "Grounded answer"
