from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.routes import ask
from tests.voice.conftest import ask_state, voice_request, voice_upload


@pytest.mark.anyio
async def test_detected_language_drives_answer_and_speechplan_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}
    monkeypatch.setattr(ask, "transcribe_voice_audio", lambda _, **kwargs: {"text": "Vad vet du?", "language": "sv"})
    monkeypatch.setattr(ask, "run_ask_graph", lambda *_, **__: ask_state("Svenskt svar. English sentence."))
    monkeypatch.setattr(ask, "get_ask_settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(ask, "load_tts_config", lambda: SimpleNamespace(enabled=True))
    def plan(**kwargs: object) -> dict[str, object]:
        seen["language"] = str(kwargs["language"])
        return {"audio_url": "/tts.wav", "voice_id": "sv_SE-lisa-medium", "segments": [{"language": "sv"}, {"language": "en"}]}
    monkeypatch.setattr(ask, "build_tts_plan", plan)
    monkeypatch.setattr(ask, "synthesize_tts", lambda **_: {"ok": False})
    result = await ask.ask_voice(voice_request(), voice_upload(), session_id=None)
    assert result.detected_language == "sv"
    assert seen["language"] == "sv"
    assert len(result.speech_plan["segments"]) == 2
