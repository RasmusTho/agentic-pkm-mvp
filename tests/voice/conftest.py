from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

from fastapi import UploadFile
import pytest
from starlette.requests import Request


WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def voice_request() -> Request:
    return Request({"type": "http", "method": "POST", "headers": []})


def voice_upload(
    payload: bytes = WAV,
    *,
    filename: str = "question.wav",
    content_type: str = "audio/wav",
) -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(payload), headers={"content-type": content_type})


def ask_state(answer: str = "Grounded answer") -> SimpleNamespace:
    return SimpleNamespace(answer=answer, hits=[])


@pytest.fixture
def voice_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real initialized selection; no voice write fixture replaces the writer."""
    from app.api.routes import ask, vault_resolution
    from app.vault.app_local import AppLocalSettingsStore
    from app.vault.manager import VaultManager

    vault = tmp_path / "voice-vault"
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    manager.initialize_vault(vault, vault_name="voice-test", remember=False)
    monkeypatch.setattr(vault_resolution, "get_vault_manager", lambda: manager)
    monkeypatch.setattr(ask, "_VOICE_SESSIONS", {})
    monkeypatch.setattr(ask, "_HYBRID_WARMED", True)
    monkeypatch.delenv("ASK_DOMAIN_SCOPE", raising=False)
    return vault


@pytest.fixture
def voice_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import ask

    monkeypatch.setattr(ask, "transcribe_voice_audio", lambda _, **__: {"text": "question", "language": "en"})
    monkeypatch.setattr(ask, "run_ask_graph", lambda *_, **__: ask_state())
    monkeypatch.setattr(ask, "get_ask_settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(ask, "load_tts_config", lambda: SimpleNamespace(enabled=False))
    monkeypatch.setattr(ask, "build_tts_plan", lambda **_: {"audio_url": "/tts.wav"})
