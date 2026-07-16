"""YSS-01 settings model (#3916, `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Settings model`).

Asserts the `youtubeSync.*` family against the production resolution and write
paths:

- defaults, scopes, and provenance resolve through ``SettingsService.resolve``
  for a freshly initialized vault (``youtube.md`` shared file + ``local.md``
  vault-local runner key), and fall back to built-in defaults when the shared
  file is absent (the existing-vault upgrade path);
- invalid values degrade to defaults with a ``SettingsValidationError``, never
  a silent apply;
- the two runtime-gating keys (``youtubeSync.enabled``,
  ``youtubeSync.runnerEnabled``) are WriteGuard-gated on write from the
  production call site (``SettingsService.update_setting``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager
from app.vault.settings_service import (
    RUNTIME_GATING_SETTINGS,
    SettingsService,
    SettingsWriteError,
)
from app.write_guard import DEFAULT_WRITE_GUARD

pytestmark = pytest.mark.not_pg


_SHARED_DEFAULTS = {
    "youtubeSync.enabled": False,
    "youtubeSync.inboxPollSeconds": 180,
    "youtubeSync.playlistPollSeconds": 3600,
    "youtubeSync.subscriptionsPollSeconds": 21600,
    "youtubeSync.reconcileIntervalDays": 7,
    "youtubeSync.maxConcurrentAcquisitions": 2,
    "youtubeSync.subscriptionDefaultPolicy": "discover_only",
    "youtubeSync.captionsEnabled": True,
    "youtubeSync.mediaDownloadEnabled": False,
}


def _initialized_vault(tmp_path: Path) -> tuple[VaultManager, Path]:
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    vault = tmp_path / "vault-primary"
    manager.initialize_vault(vault, machine_role="primary", remember=False)
    return manager, vault


def test_defaults_scopes_provenance_and_gated_writes(tmp_path: Path, monkeypatch) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))

    manager, vault = _initialized_vault(tmp_path)
    context = manager.context
    settings_dir = vault / "settings"
    service = SettingsService()

    # --- defaults, scopes, and provenance from a freshly initialized vault ---
    assert (settings_dir / "youtube.md").exists(), "initialize_vault must provision settings/youtube.md"
    resolution = service.resolve(context)
    settings = resolution.settings
    for key, default in _SHARED_DEFAULTS.items():
        effective = settings[key]
        assert effective.value == default, key
        assert effective.scope == "vault-shared", key
        assert effective.source.endswith("youtube.md"), key
    runner = settings["youtubeSync.runnerEnabled"]
    assert runner.value is False
    assert runner.scope == "vault-local"
    assert runner.source.endswith("local.md")
    assert not [err for err in resolution.validation_errors if (err.key or "").startswith("youtubeSync.")]

    # --- the two gating keys are WriteGuard-gated at the production call site ---
    assert {"youtubeSync.enabled", "youtubeSync.runnerEnabled"} <= set(RUNTIME_GATING_SETTINGS)
    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "safe_mode", "reason": "test-block"}
    )
    for gated_key in ("youtubeSync.enabled", "youtubeSync.runnerEnabled"):
        with pytest.raises(SettingsWriteError, match="blocked"):
            service.update_setting(context, gated_key, True, surface="api", actor="human")
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "healthy"})
    effective, receipt = service.update_setting(
        context, "youtubeSync.enabled", True, surface="api", actor="human"
    )
    assert effective.value is True
    assert receipt.is_runtime_gating is True
    assert receipt.file.endswith("youtube.md")
    effective, receipt = service.update_setting(
        context, "youtubeSync.runnerEnabled", True, surface="cli", actor="human"
    )
    assert effective.value is True
    assert receipt.is_runtime_gating is True
    assert receipt.file.endswith("local.md")

    # A non-gating key writes without the guard seam (still validated).
    effective, receipt = service.update_setting(
        context, "youtubeSync.inboxPollSeconds", 300, surface="api", actor="human"
    )
    assert effective.value == 300
    assert receipt.is_runtime_gating is False

    # Write-time validation rejects out-of-bounds values loudly.
    with pytest.raises(SettingsWriteError):
        service.update_setting(context, "youtubeSync.inboxPollSeconds", 30, surface="api", actor="human")
    with pytest.raises(SettingsWriteError):
        service.update_setting(
            context, "youtubeSync.subscriptionDefaultPolicy", "cookie_mode", surface="api", actor="human"
        )

    # --- missing shared file (existing-vault upgrade path): built-in defaults apply ---
    (settings_dir / "youtube.md").unlink()
    resolution = service.resolve(context)
    for key, default in _SHARED_DEFAULTS.items():
        effective = resolution.settings[key]
        assert effective.value == default, key
        assert effective.scope == "built-in", key
        assert effective.source == "built-in", key

    # --- invalid values degrade to defaults with a validation error, never silently ---
    (settings_dir / "youtube.md").write_text(
        "---\n"
        "schema: design-handoff.youtube-sync.v1\n"
        "scope: vault-shared\n"
        "youtubeSync.inboxPollSeconds: 5\n"
        "youtubeSync.subscriptionsPollSeconds: 999999\n"
        "youtubeSync.subscriptionDefaultPolicy: cookie_mode\n"
        "youtubeSync.playlistPollSeconds: 7200\n"
        "---\n# YouTube Sync Settings\n",
        encoding="utf-8",
    )
    resolution = service.resolve(context)
    settings = resolution.settings
    assert settings["youtubeSync.inboxPollSeconds"].value == 180
    assert settings["youtubeSync.inboxPollSeconds"].scope == "built-in"
    assert settings["youtubeSync.subscriptionsPollSeconds"].value == 21600
    assert settings["youtubeSync.subscriptionDefaultPolicy"].value == "discover_only"
    # The valid key from the same file still applies with file provenance.
    assert settings["youtubeSync.playlistPollSeconds"].value == 7200
    assert settings["youtubeSync.playlistPollSeconds"].source.endswith("youtube.md")
    error_keys = {err.key for err in resolution.validation_errors}
    assert {
        "youtubeSync.inboxPollSeconds",
        "youtubeSync.subscriptionsPollSeconds",
        "youtubeSync.subscriptionDefaultPolicy",
    } <= error_keys
