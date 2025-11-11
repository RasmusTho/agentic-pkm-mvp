from __future__ import annotations

import pytest

from app.diarization.hook import apply_diarization

pytestmark = pytest.mark.not_pg


def test_diarization_disabled_returns_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DIARIZE_ENABLE", raising=False)
    payload = {"text": "hello world", "segments": [{"speaker": "spk_0", "text": "hello world"}]}
    assert apply_diarization(payload) == payload


def test_mock_diarizer_creates_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIARIZE_ENABLE", "1")
    monkeypatch.setenv("DIARIZE_PROVIDER", "mock")
    payload = {"text": "Alpha speaks first. Beta responds with details."}
    out = apply_diarization(payload)
    assert len(out["segments"]) >= 2
    speakers = {seg["speaker"] for seg in out["segments"]}
    assert "spk_0" in speakers and "spk_1" in speakers


def test_external_diarizer_uses_http(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.diarization import hook as hook_mod

    monkeypatch.setenv("DIARIZE_ENABLE", "1")
    monkeypatch.setenv("DIARIZE_PROVIDER", "external")
    monkeypatch.setenv("DIARIZE_HTTP_ENDPOINT", "https://diarize.local")

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "segments": [
                    {"speaker": "external-a", "text": "Hello"},
                    {"speaker": "external-b", "text": "World"},
                ]
            }

    def fake_post(url, json, timeout):
        assert url == "https://diarize.local"
        return DummyResponse()

    monkeypatch.setattr(hook_mod.httpx, "post", fake_post)
    payload = {"text": "Hello world."}
    out = apply_diarization(payload)
    assert [seg["speaker"] for seg in out["segments"]] == ["external-a", "external-b"]
