from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes import ask
from tests.voice.conftest import ask_state, voice_request, voice_upload


@pytest.mark.anyio
async def test_audio_limits_rejected_legibly(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False
    def should_not_run(_: bytes) -> dict[str, str]:
        nonlocal called
        called = True
        return {}
    monkeypatch.setattr(ask, "transcribe_voice_audio", should_not_run)
    with pytest.raises(HTTPException) as oversize:
        await ask.ask_voice(voice_request(), voice_upload(b"RIFF\x00\x00\x00\x00WAVE" + b"x" * ask.VOICE_ASK_MAX_AUDIO_BYTES), session_id=None)
    assert oversize.value.status_code == 413
    assert oversize.value.detail["error"] == "audio_too_large"
    with pytest.raises(HTTPException) as undecodable:
        await ask.ask_voice(voice_request(), voice_upload(b"not-audio"), session_id=None)
    assert undecodable.value.status_code == 415
    assert undecodable.value.detail["error"] == "audio_undecodable"
    assert not called


@pytest.mark.anyio
async def test_accepted_container_uses_content_type_not_generic_filename(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}
    monkeypatch.setattr(ask, "transcribe_voice_audio", lambda _, **kwargs: seen.update(kwargs) or {"text": "hello", "language": "en"})
    monkeypatch.setattr(ask, "run_ask_graph", lambda *_, **__: ask_state())
    monkeypatch.setattr(ask, "get_ask_settings", lambda: object())
    monkeypatch.setattr(ask, "load_tts_config", lambda: type("Config", (), {"enabled": False})())
    monkeypatch.setattr(ask, "build_tts_plan", lambda **_: {"audio_url": "/tts.wav"})
    result = await ask.ask_voice(
        voice_request(),
        voice_upload(b"\x1aE\xdf\xa3webm", filename="blob", content_type="audio/webm"),
        session_id=None,
    )
    assert result.answer == "Grounded answer"
    assert seen["suffix"] == ".webm"


@pytest.mark.anyio
async def test_voice_turn_binds_the_request_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """A voice turn must not be a scope-isolation hole just because it arrives as form data (#2921).

    Without this, deleting `active_scope=scope` from the voice `run_ask_graph` call leaves the
    whole suite green: every other voice test monkeypatches `run_ask_graph` away entirely.
    """
    seen: dict[str, object] = {}

    def _capture_run_ask_graph(*_args, **kwargs):
        seen.update(kwargs)
        return ask_state()

    monkeypatch.setattr(
        ask, "transcribe_voice_audio", lambda _, **__: {"text": "what did I decide", "language": "en"}
    )
    monkeypatch.setattr(ask, "run_ask_graph", _capture_run_ask_graph)
    monkeypatch.setattr(ask, "get_ask_settings", lambda: object())
    monkeypatch.setattr(ask, "load_tts_config", lambda: type("Config", (), {"enabled": False})())
    monkeypatch.setattr(ask, "build_tts_plan", lambda **_: {"audio_url": "/tts.wav"})

    result = await ask.ask_voice(
        voice_request(),
        voice_upload(b"RIFF\x00\x00\x00\x00WAVE", content_type="audio/wav"),
        session_id=None,
        scope="work",
    )

    assert result.answer == "Grounded answer"
    assert seen.get("active_scope") == "work", (
        f"the voice form's scope must reach run_ask_graph, saw {seen.get('active_scope')!r}"
    )
