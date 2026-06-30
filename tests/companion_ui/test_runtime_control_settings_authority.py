"""Guard test: runtime-gating setting writes route through the governed write seam.

AC2 of #2475 — task: charter the Companion-UI runtime-control-action boundary.

``enableVaultWatcher`` and ``enableAutoIndexing`` are authority-bearing in the
proportional sense: they reconfigure whether the watcher/indexing runtime runs
(``app/watcher/registry.py:734``, ``app/watcher/config.py:92``).

The write must route through ONE server-side governed seam:
1. WriteGuard health-gate is asserted before the markdown write.
2. An actor-tagged SettingsWriteReceipt is emitted (who / which surface / when).

This test exercises the production write path (``POST /api/companion/vault/settings``
→ ``SettingsService.update_setting``) and verifies:
- The seam is the governed one (WriteGuard is consulted for runtime-gating keys).
- A SettingsWriteReceipt is emitted with correct surface/actor metadata.
- Non-runtime-gating settings bypass the WriteGuard (plain write, no gate).
- When WriteGuard blocks (health=safe_mode), runtime-gating writes are rejected.

Patterns borrowed from ``tests/companion_ui/test_vault_settings_editor.py``
and ``tests/companion_ui/test_vault_settings_panel.py``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import os

import yaml
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import companion as companion_module
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager
from app.vault.settings_service import (
    RUNTIME_GATING_SETTINGS,
    SettingsService,
    SettingsWriteReceipt,
)
from app.vault.markdown_settings import MarkdownSettingsStore
from app.watcher.config import WatcherConfig
from app.watcher.state import WatcherState
from app.watcher.watcher import run_tick


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _manager(tmp_path: Path) -> tuple[VaultManager, Path]:
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    vault = tmp_path / "vault-primary"
    manager.initialize_vault(vault, machine_role="primary", remember=False)
    return manager, vault


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]
    data = yaml.safe_load(frontmatter)
    assert isinstance(data, dict)
    return data


def _write_frontmatter(path: Path, updates: dict) -> None:
    store = MarkdownSettingsStore()
    document = store.read(path)
    frontmatter = dict(document.frontmatter)
    frontmatter.update(updates)
    store.write_frontmatter(path, frontmatter, body=document.body)


def _watcher_config(tmp_path: Path, vault: Path) -> WatcherConfig:
    return WatcherConfig(
        enable=True,
        vault_path=vault,
        scope_glob="*.md,**/*.md",
        debounce_ms=0,
        rate_limit_per_min=30,
        backoff_seconds=10,
        state_path=tmp_path / "watcher-state.json",
        stop_file=tmp_path / "WATCHER_STOP",
        outbox_path=tmp_path / "watcher-outbox.jsonl",
        summary_interval=10,
        tick_sleep_seconds=0.0,
        tick_log_path=tmp_path / "watcher-tick.jsonl",
    )


def _touch_after_write(path: Path, timestamp: float) -> None:
    os.utime(path, (timestamp, timestamp))


# ---------------------------------------------------------------------------
# Unit-level tests (SettingsService directly)
# ---------------------------------------------------------------------------


def test_runtime_gating_setting_write_is_governed(tmp_path: Path) -> None:
    """POST /api/companion/vault/settings for a runtime-gating key routes through
    the governed write seam (WriteGuard + actor receipt).

    This is the primary AC2 test — it exercises the production write path end-to-end
    via the TestClient (same route used by the Companion UI).
    """
    manager, vault = _manager(tmp_path)
    monkeypatch_target = companion_module

    captured_receipts: list[SettingsWriteReceipt] = []
    original_update = SettingsService.update_setting

    def _spy_update(
        self: SettingsService, context, key, value, *, surface="api", actor="human", persist=True
    ):
        result, receipt = original_update(
            self, context, key, value, surface=surface, actor=actor, persist=persist
        )
        captured_receipts.append(receipt)
        return result, receipt

    with (
        patch.object(monkeypatch_target, "get_vault_manager", return_value=manager),
        patch.object(SettingsService, "update_setting", _spy_update),
    ):
        client = TestClient(app)
        response = client.post(
            "/api/companion/vault/settings",
            json={"key": "enableVaultWatcher", "value": False},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["updated"]["key"] == "enableVaultWatcher"
    assert payload["updated"]["value"] is False

    # A receipt was emitted and carries the correct metadata.
    assert len(captured_receipts) == 1
    receipt = captured_receipts[0]
    assert receipt.key == "enableVaultWatcher"
    assert receipt.value is False
    assert receipt.surface == "api"
    assert receipt.actor == "human"
    assert receipt.is_runtime_gating is True

    # The write landed in the vault settings file.
    assert _frontmatter(vault / "settings" / "local.md")["enableVaultWatcher"] is False


def test_auto_indexing_setting_write_is_governed(tmp_path: Path) -> None:
    """``enableAutoIndexing`` is also a runtime-gating key and must carry a receipt."""
    manager, vault = _manager(tmp_path)
    captured_receipts: list[SettingsWriteReceipt] = []
    original_update = SettingsService.update_setting

    def _spy_update(
        self: SettingsService, context, key, value, *, surface="api", actor="human", persist=True
    ):
        result, receipt = original_update(
            self, context, key, value, surface=surface, actor=actor, persist=persist
        )
        captured_receipts.append(receipt)
        return result, receipt

    with (
        patch.object(companion_module, "get_vault_manager", return_value=manager),
        patch.object(SettingsService, "update_setting", _spy_update),
    ):
        client = TestClient(app)
        response = client.post(
            "/api/companion/vault/settings",
            json={"key": "enableAutoIndexing", "value": False},
        )

    assert response.status_code == 200, response.text
    assert len(captured_receipts) == 1
    receipt = captured_receipts[0]
    assert receipt.is_runtime_gating is True
    assert receipt.key == "enableAutoIndexing"
    assert _frontmatter(vault / "settings" / "local.md")["enableAutoIndexing"] is False


def test_non_runtime_gating_setting_write_emits_receipt_not_gated(tmp_path: Path) -> None:
    """Non-runtime-gating settings (e.g. handoffFolder) also emit a receipt but
    do NOT assert the WriteGuard (no authority-bearing classification).
    """
    manager, vault = _manager(tmp_path)
    captured_receipts: list[SettingsWriteReceipt] = []
    original_update = SettingsService.update_setting

    def _spy_update(
        self: SettingsService, context, key, value, *, surface="api", actor="human", persist=True
    ):
        result, receipt = original_update(
            self, context, key, value, surface=surface, actor=actor, persist=persist
        )
        captured_receipts.append(receipt)
        return result, receipt

    with (
        patch.object(companion_module, "get_vault_manager", return_value=manager),
        patch.object(SettingsService, "update_setting", _spy_update),
    ):
        client = TestClient(app)
        response = client.post(
            "/api/companion/vault/settings",
            json={"key": "handoffFolder", "value": "Client Projects"},
        )

    assert response.status_code == 200, response.text
    assert len(captured_receipts) == 1
    receipt = captured_receipts[0]
    assert receipt.is_runtime_gating is False
    assert receipt.key == "handoffFolder"


def test_write_guard_blocks_runtime_gating_write_in_safe_mode(tmp_path: Path) -> None:
    """When the system is in safe_mode the WriteGuard blocks runtime-gating writes.

    The API must propagate the block as a 400 (SettingsWriteError from the seam).

    We patch ``DEFAULT_WRITE_GUARD.snapshot_fn`` directly because the singleton
    captures a bound method reference at import time; patching DEFAULT_CONTRACT
    would have no effect on the already-bound callable.
    """
    import app.write_guard as _wg_module

    manager, _vault = _manager(tmp_path)
    blocked_snapshot = {"state": "safe_mode", "reason": "maintenance window"}

    with (
        patch.object(companion_module, "get_vault_manager", return_value=manager),
        patch.object(_wg_module.DEFAULT_WRITE_GUARD, "snapshot_fn", return_value=blocked_snapshot),
    ):
        client = TestClient(app)
        response = client.post(
            "/api/companion/vault/settings",
            json={"key": "enableVaultWatcher", "value": False},
        )

    assert response.status_code == 400
    assert "blocked" in response.text.lower() or "health gate" in response.text.lower()


def test_write_guard_does_not_block_non_runtime_gating_in_safe_mode(tmp_path: Path) -> None:
    """The WriteGuard is NOT applied for non-runtime-gating settings.
    A safe_mode system should still allow regular settings writes.
    """
    import app.write_guard as _wg_module

    manager, vault = _manager(tmp_path)
    blocked_snapshot = {"state": "safe_mode", "reason": "maintenance window"}

    with (
        patch.object(companion_module, "get_vault_manager", return_value=manager),
        patch.object(_wg_module.DEFAULT_WRITE_GUARD, "snapshot_fn", return_value=blocked_snapshot),
    ):
        client = TestClient(app)
        response = client.post(
            "/api/companion/vault/settings",
            json={"key": "handoffFolder", "value": "Safe Mode Projects"},
        )

    assert response.status_code == 200, response.text
    assert _frontmatter(vault / "settings" / "paths.md")["handoffFolder"] == "Safe Mode Projects"


# ---------------------------------------------------------------------------
# Unit-level tests (SettingsService directly, without HTTP layer)
# ---------------------------------------------------------------------------


def test_settings_service_update_returns_receipt(tmp_path: Path) -> None:
    """SettingsService.update_setting returns (EffectiveSetting, SettingsWriteReceipt)."""
    manager, vault = _manager(tmp_path)
    context = manager.context

    service = SettingsService()
    result = service.update_setting(context, "enableVaultWatcher", False, surface="cli", actor="human")

    assert isinstance(result, tuple), "update_setting must return a 2-tuple"
    effective, receipt = result
    assert effective.key == "enableVaultWatcher"
    assert effective.value is False
    assert isinstance(receipt, SettingsWriteReceipt)
    assert receipt.surface == "cli"
    assert receipt.actor == "human"
    assert receipt.is_runtime_gating is True
    assert receipt.timestamp  # non-empty ISO timestamp


def test_runtime_gating_settings_constant_covers_both_keys() -> None:
    """RUNTIME_GATING_SETTINGS must enumerate both authority-bearing runtime-gating keys."""
    assert "enableVaultWatcher" in RUNTIME_GATING_SETTINGS
    assert "enableAutoIndexing" in RUNTIME_GATING_SETTINGS


def test_watcher_settings_delta_routes_runtime_gating_key_through_settings_service(tmp_path: Path) -> None:
    manager, vault = _manager(tmp_path)
    del manager
    cfg = _watcher_config(tmp_path, vault)
    state = WatcherState()
    local_md = vault / "settings" / "local.md"
    captured_calls: list[tuple[str, object, str, str]] = []
    original_update = SettingsService.update_setting

    def _spy_update(
        self: SettingsService, context, key, value, *, surface="api", actor="human", persist=True
    ):
        captured_calls.append((key, value, surface, actor))
        return original_update(self, context, key, value, surface=surface, actor=actor, persist=persist)

    first = run_tick(cfg, state, now=1_700_000_000.0)
    assert first["changed_in_tick"] >= 1

    _write_frontmatter(local_md, {"enableVaultWatcher": False})
    _touch_after_write(local_md, 1_700_000_010.0)

    with patch.object(SettingsService, "update_setting", _spy_update):
        second = run_tick(cfg, state, now=1_700_000_010.0)

    assert second["settings_receipts_in_tick"] == 1
    assert captured_calls == [("enableVaultWatcher", False, "file", "human")]


def test_watcher_settings_delta_emits_file_surface_receipt(tmp_path: Path) -> None:
    manager, vault = _manager(tmp_path)
    del manager
    cfg = _watcher_config(tmp_path, vault)
    state = WatcherState()
    local_md = vault / "settings" / "local.md"
    captured_receipts: list[SettingsWriteReceipt] = []
    original_update = SettingsService.update_setting

    def _spy_update(
        self: SettingsService, context, key, value, *, surface="api", actor="human", persist=True
    ):
        effective, receipt = original_update(
            self, context, key, value, surface=surface, actor=actor, persist=persist
        )
        captured_receipts.append(receipt)
        return effective, receipt

    run_tick(cfg, state, now=1_700_000_000.0)
    _write_frontmatter(local_md, {"enableAutoIndexing": False})
    _touch_after_write(local_md, 1_700_000_020.0)

    with patch.object(SettingsService, "update_setting", _spy_update):
        run_tick(cfg, state, now=1_700_000_020.0)

    assert len(captured_receipts) == 1
    receipt = captured_receipts[0]
    assert receipt.key == "enableAutoIndexing"
    assert receipt.value is False
    assert receipt.surface == "file"
    assert receipt.actor == "human"
    assert receipt.is_runtime_gating is True


def test_watcher_settings_delta_receipt_scope_is_runtime_gating_only(tmp_path: Path) -> None:
    manager, vault = _manager(tmp_path)
    del manager
    cfg = _watcher_config(tmp_path, vault)
    state = WatcherState()
    local_md = vault / "settings" / "local.md"
    captured_receipts: list[SettingsWriteReceipt] = []
    original_update = SettingsService.update_setting

    def _spy_update(
        self: SettingsService, context, key, value, *, surface="api", actor="human", persist=True
    ):
        effective, receipt = original_update(
            self, context, key, value, surface=surface, actor=actor, persist=persist
        )
        captured_receipts.append(receipt)
        return effective, receipt

    run_tick(cfg, state, now=1_700_000_000.0)
    _write_frontmatter(local_md, {"allowWritesToVault": False})
    _touch_after_write(local_md, 1_700_000_030.0)

    with patch.object(SettingsService, "update_setting", _spy_update):
        summary = run_tick(cfg, state, now=1_700_000_030.0)

    assert summary.get("settings_receipts_in_tick", 0) == 0
    assert captured_receipts == []
