"""Cross-process settings reload signal path and delivery behavior."""

from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from app.settings.reload_signal import publish_reload_signal, read_reload_signal, signal_path

pytestmark = pytest.mark.not_pg


def test_signal_path_follows_channel_runtime_artifact_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compose's test-channel artifact mount is also the reload bus mount."""
    monkeypatch.delenv("SETTINGS_RELOAD_SIGNAL_PATH", raising=False)
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", "/app/tmp-test/watcher_heartbeat.json")

    assert signal_path() == Path("/app/tmp-test/settings-reload.json")


def test_signal_path_uses_writable_local_fallback_without_runtime_topology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raw pytest/local processes do not assume an /app runtime volume exists."""
    monkeypatch.delenv("SETTINGS_RELOAD_SIGNAL_PATH", raising=False)
    monkeypatch.delenv("WATCHER_HEARTBEAT_PATH", raising=False)

    assert signal_path() == Path(tempfile.gettempdir()) / "agentic-pkm/settings-reload.json"


def test_explicit_signal_path_is_published_and_read_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "cross-process" / "settings-reload.json"
    monkeypatch.setenv("SETTINGS_RELOAD_SIGNAL_PATH", str(target))

    published = publish_reload_signal(
        state="ok", source="vault", loaded_at="2026-07-13T00:00:00Z", error=None
    )

    assert target.exists()
    assert read_reload_signal() == published
