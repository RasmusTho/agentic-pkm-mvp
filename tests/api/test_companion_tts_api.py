from __future__ import annotations

import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.tts.providers import TTSVoice


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    model_dir = tmp_path / "models"
    piper_dir = model_dir / "piper" / "sv_SE-nst-medium"
    kokoro_dir = model_dir / "kokoro"
    piper_dir.mkdir(parents=True)
    kokoro_dir.mkdir(parents=True)
    (piper_dir / "sv_SE-nst-medium.onnx").write_bytes(b"model")
    (piper_dir / "sv_SE-nst-medium.onnx.json").write_text("{}", encoding="utf-8")
    (kokoro_dir / "kokoro-v1.0.int8.onnx").write_bytes(b"model")
    (kokoro_dir / "voices-v1.0.bin").write_bytes(b"voice")
    monkeypatch.setenv("TTS_ENABLED", "true")
    monkeypatch.setenv("TTS_LOCAL_ONLY", "true")
    monkeypatch.setenv("TTS_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TTS_CACHE_MAX_GB", "2")
    monkeypatch.setenv("TTS_CACHE_EVICTION", "lru")
    monkeypatch.setenv("TTS_MAX_CONCURRENT_JOBS", "1")
    monkeypatch.setenv("TTS_MAX_CHARS_PER_REQUEST", "4000")
    monkeypatch.setenv("TTS_ALLOW_BROWSER_FALLBACK", "false")
    monkeypatch.setenv("TTS_ALLOW_CLOUD_FALLBACK", "false")
    monkeypatch.setenv("TTS_PIPER_COMMAND", "/bin/echo")
    return TestClient(app)


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 160)


def test_plan_endpoint_is_local_only(client: TestClient) -> None:
    resp = client.post("/api/companion/tts/plan", json={"text": "Hej världen."})

    assert resp.status_code == 200
    data = resp.json()
    assert data["local_only"] is True
    assert data["allow_browser_fallback"] is False
    assert data["allow_cloud_fallback"] is False
    assert data["provider"] == "piper"
    assert data["audio_url"].startswith("/api/companion/tts/audio/")


def test_synthesize_uses_cache_on_repeat(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, float]] = []

    def fake_synthesize(
        text: str,
        voice: TTSVoice,
        output_path: Path,
        *,
        rate: float = 1.0,
    ) -> None:
        calls.append((text, voice.voice_id, rate))
        _write_wav(output_path)

    monkeypatch.setattr("app.tts.service.synthesize_with_voice", fake_synthesize)

    first = client.post("/api/companion/tts/synthesize", json={"text": "Hej världen.", "rate": 1.35})
    second = client.post("/api/companion/tts/synthesize", json={"text": "Hej världen.", "rate": 1.35})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["state"] == "generated"
    assert second.json()["state"] == "cached"
    assert first.json()["cache_key"] == second.json()["cache_key"]
    assert calls == [("Hej världen.", "sv_SE-nst-medium", 1.35)]

    audio = client.get(first.json()["audio_url"])
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/wav")
    assert audio.content.startswith(b"RIFF")


def test_synthesize_refuses_missing_local_provider(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TTS_PIPER_COMMAND", raising=False)
    monkeypatch.setenv("PATH", "")

    resp = client.post("/api/companion/tts/synthesize", json={"text": "Hej världen."})

    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["ok"] is False
    assert "piper command" in detail["reason"]


def test_synthesize_returns_structured_unavailable_on_provider_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_synthesize(
        text: str,
        voice: TTSVoice,
        output_path: Path,
        *,
        rate: float = 1.0,
    ) -> None:
        raise RuntimeError("local model failed")

    monkeypatch.setattr("app.tts.service.synthesize_with_voice", failing_synthesize)

    resp = client.post("/api/companion/tts/synthesize", json={"text": "Hej världen."})

    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["ok"] is False
    assert detail["state"] == "unavailable"
    assert "provider_execution_failed" in detail["reason"]
    assert "local model failed" in detail["reason"]
