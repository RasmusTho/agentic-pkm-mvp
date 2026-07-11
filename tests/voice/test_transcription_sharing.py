"""VOICE-02 fitness tests for the single shared ASR engine."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app.heimdal.asr_stage import LocalAsrUnavailableError
from app.media import transcribe
from app.voice import transcription


def test_voice_path_calls_shared_run_asr(monkeypatch: pytest.MonkeyPatch) -> None:
    """The production voice seam calls the existing media engine directly."""

    observed: dict[str, Path] = {}

    def fake_run_asr(path: Path) -> dict[str, object]:
        observed["path"] = path
        return {"text": "hej", "segments": [], "language": "sv"}

    monkeypatch.setattr(transcription, "run_asr", fake_run_asr)

    result = transcription.transcribe_voice_wav(b"wav bytes")

    assert result["text"] == "hej"
    assert transcribe.run_asr.__module__ == "app.media.transcribe"
    assert not observed["path"].exists()
    source = inspect.getsource(transcription)
    assert "from app.media.transcribe import run_asr" in source


def test_single_asr_engine_owner() -> None:
    """Only app.media.transcribe may construct a faster-whisper model."""

    app_root = Path(__file__).resolve().parents[2] / "app"
    owners: list[Path] = []
    for path in app_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports_whisper = any(
            isinstance(node, ast.ImportFrom) and node.module == "faster_whisper"
            for node in ast.walk(tree)
        )
        constructs_whisper = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "WhisperModel"
            for node in ast.walk(tree)
        )
        if imports_whisper or constructs_whisper:
            owners.append(path.relative_to(app_root.parent))

    assert owners == [Path("app/media/transcribe.py")], f"unexpected ASR engine owner(s): {owners}"


def test_voice_path_is_ephemeral_and_ungated(monkeypatch: pytest.MonkeyPatch) -> None:
    """A voice query creates no Heimdal raw record and leaves no WAV behind."""

    observed: dict[str, Path] = {}

    def fake_run_asr(path: Path) -> dict[str, object]:
        observed["path"] = path
        assert path.exists()
        return {"text": "question", "segments": [], "language": "en"}

    monkeypatch.setattr(transcription, "run_asr", fake_run_asr)

    transcription.transcribe_voice_wav(b"ephemeral wav")

    assert not observed["path"].exists()
    assert "read_raw_record(" not in inspect.getsource(transcription)


def test_voice_path_posture_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Voice inherits local-only, auto-language, fail-loud ASR behavior."""

    def unavailable(_: Path) -> dict[str, object]:
        raise RuntimeError("faster-whisper unavailable")

    monkeypatch.setattr(transcription, "run_asr", unavailable)

    with pytest.raises(LocalAsrUnavailableError, match="Shared local ASR engine"):
        transcription.transcribe_voice_wav(b"local only")

    source = inspect.getsource(transcription).lower()
    assert "language=" not in source
    for forbidden in ("openai.audio", "cloud_asr", "whisper_api", "azure_speech", "google.cloud.speech"):
        assert forbidden not in source
