"""Shared helpers to bind a *selected* vault in companion API tests (#2309).

Option-2 (decision 2026-06-20): a configured ``VAULT_ROOT`` is no longer
silently the active vault. Tests that exercise the active-vault read/write
boundaries must select (or initialize) a vault, mirroring the human picking one
in the UI. These helpers replace the bare ``monkeypatch.setenv("VAULT_ROOT", …)``
setup that relied on the removed read-fallback.

- :func:`bind_selected_vault` selects a bare directory (``uninitialized``):
  reads work; writes/permissions still require initialization. Use for
  browse / orientation / read-only workspace tests.
- :func:`bind_initialized_vault` initializes + selects (``selected``, with
  Design-Handoff settings): reads *and* writes/permissions work. Use for
  workspace-update / body-update / permission tests.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import app.api.routes.companion as companion_module
import app.api.routes.vault_resolution as vault_resolution_module
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager


def _fresh_manager(monkeypatch: pytest.MonkeyPatch, store_dir: Path) -> VaultManager:
    # Dot-prefixed app-local file so it never leaks into vault enumeration even
    # when ``store_dir`` is the vault root itself.
    app_local_path = store_dir / ".app-local.md"
    monkeypatch.setenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", str(app_local_path))
    mgr = VaultManager(app_local_store=AppLocalSettingsStore(app_local_path))
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: mgr)
    monkeypatch.setattr(vault_resolution_module, "get_vault_manager", lambda: mgr)
    if hasattr(mgr, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR):
        delattr(mgr, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR)
    return mgr


def _set_env(monkeypatch: pytest.MonkeyPatch, vault_root: Path, channel: str) -> None:
    monkeypatch.setenv("PKM_ENVIRONMENT", channel)
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)


def bind_selected_vault(
    monkeypatch: pytest.MonkeyPatch,
    vault_root: Path,
    *,
    channel: str = "dev",
    store_dir: Path | None = None,
) -> VaultManager:
    """Select ``vault_root`` as the active (read-capable) vault.

    A bare directory selects as ``uninitialized`` — reads work; writes and
    permissions still require initialization.
    """
    _set_env(monkeypatch, vault_root, channel)
    mgr = _fresh_manager(monkeypatch, store_dir or vault_root)
    mgr.select_vault(vault_root, remember=False)
    return mgr


def bind_initialized_vault(
    monkeypatch: pytest.MonkeyPatch,
    vault_root: Path,
    *,
    name: str = "Test Vault",
    channel: str = "dev",
    store_dir: Path | None = None,
) -> VaultManager:
    """Initialize + select ``vault_root`` (``selected``, write-capable)."""
    _set_env(monkeypatch, vault_root, channel)
    mgr = _fresh_manager(monkeypatch, store_dir or vault_root)
    mgr.initialize_vault(vault_root, vault_name=name, remember=False)
    return mgr
