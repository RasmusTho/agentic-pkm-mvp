from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes import ask
from tests.voice.conftest import voice_request, voice_upload


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
