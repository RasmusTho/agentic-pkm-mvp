"""Regression tests for vault init/preflight/registry residuals (issue #2185).

Each test exercises the production call path for one acceptance criterion:

- AC1: ``vault init --machine-role satellite`` is accepted by the CLI choice list.
- AC2: ``vault_settings_preflight`` blocks a ``selected`` vault whose settings
  disable the watcher (would fail-exit at startup, app/watcher/config.py:92-93).
- AC3: selecting a vault with ``remember=True`` over a corrupt app-local
  registry recovers (backs up + re-seeds) instead of 500ing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from app.cli.vault import vault as vault_cli
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager
from app.vault.markdown_settings import MarkdownSettingsError, MarkdownSettingsStore
from app.vault.promotion_preflight import vault_settings_preflight


def _manager(tmp_path: Path) -> VaultManager:
    return VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))


# --- AC1: satellite role is a valid vault-init choice ------------------------


def test_vault_init_accepts_satellite_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`vault init --machine-role satellite` is accepted and writes the role.

    Before the fix `satellite` was absent from the CLI choice list, so click
    rejected it with a non-zero "Invalid value" exit (exercising the production
    `click.Choice(_ROLES)` gate).
    """

    monkeypatch.setenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", str(tmp_path / "app-local.md"))
    import app.vault.manager as vault_manager_module

    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)

    vault = tmp_path / "vault"
    result = CliRunner().invoke(
        vault_cli,
        ["init", "--path", str(vault), "--machine-role", "satellite"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert "Invalid value" not in result.output
    local_doc = MarkdownSettingsStore().read(vault / "settings" / "local.md")
    assert local_doc.frontmatter["machineRole"] == "satellite"


def test_vault_init_satellite_in_help_choices() -> None:
    """The satellite role is offered in the CLI choice list (help surface)."""

    result = CliRunner().invoke(vault_cli, ["init", "--help"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "satellite" in result.output


# --- AC2: preflight blocks a watcher-disabled selected vault -----------------


def _disable_watcher_in_local(vault: Path) -> None:
    store = MarkdownSettingsStore()
    local_path = vault / "settings" / "local.md"
    doc = store.read(local_path)
    frontmatter = dict(doc.frontmatter)
    frontmatter["enableVaultWatcher"] = False
    store.write_frontmatter(local_path, frontmatter, body=doc.body)


def test_preflight_clears_watcher_enabled_vault(tmp_path: Path) -> None:
    """A normal initialized vault (watcher enabled) is non-blocking."""

    vault = tmp_path / "vault"
    _manager(tmp_path).initialize_vault(vault, remember=False)

    pf = vault_settings_preflight(vault)

    assert pf.status == "selected"
    assert pf.initialized is True
    assert pf.blocking is False


def test_preflight_blocks_when_watcher_disabled(tmp_path: Path) -> None:
    """A `selected` vault whose settings disable the watcher must block.

    config.py:92-93 fail-exits the runtime for such a vault, so prepare-promotion
    must not green-light it. Before the fix `blocking` was False because the
    status was `selected`.
    """

    vault = tmp_path / "vault"
    _manager(tmp_path).initialize_vault(vault, remember=False)
    _disable_watcher_in_local(vault)

    pf = vault_settings_preflight(vault)

    assert pf.status == "selected"
    assert pf.initialized is True
    assert pf.blocking is True
    assert pf.remedy is not None
    assert "local.md" in pf.remedy


# --- AC3: picker recovery from a corrupt app-local registry ------------------


_CORRUPT_REGISTRY = (
    "---\n"
    "<<<<<<< HEAD\n"
    "schema: design-handoff.app-local.v1\n"
    "=======\n"
    "schema: other\n"
    ">>>>>>> branch\n"
    "---\n"
)


def test_select_remember_recovers_from_corrupt_registry(tmp_path: Path) -> None:
    """`select_vault(remember=True)` over a corrupt registry recovers, no raise.

    This is the production path behind POST /vault/select (remember defaults to
    True). Before the fix, `upsert_known_vault` -> load() -> read() re-raised
    `MarkdownSettingsError`, surfacing as a 500.
    """

    registry_path = tmp_path / "app-local.md"
    vault = tmp_path / "vault"
    # Initialize the vault first while the registry is still clean.
    manager = _manager(tmp_path)
    manager.initialize_vault(vault, remember=False)

    # Corrupt the registry, then select with remember=True.
    registry_path.write_text(_CORRUPT_REGISTRY, encoding="utf-8")

    # Sanity: the corrupt registry is genuinely unreadable before the select.
    with pytest.raises(MarkdownSettingsError):
        AppLocalSettingsStore(registry_path).load()

    context = manager.select_vault(vault, remember=True)

    assert context.status == "selected"
    # The corrupt file was backed up aside, and a fresh registry now records
    # the selection as the active vault.
    backups = list(tmp_path.glob("app-local.md.corrupt-*"))
    assert backups, "corrupt registry should be backed up"
    reloaded = AppLocalSettingsStore(registry_path).load()
    assert reloaded.last_active_vault_ref is not None
    assert reloaded.last_active_vault_ref in reloaded.known_vaults


def test_initialize_remember_recovers_from_corrupt_registry(tmp_path: Path) -> None:
    """`initialize_vault(remember=True)` over a corrupt registry recovers too.

    POST /vault/initialize also defaults remember=True and runs the same
    `_remember_context` -> `upsert_known_vault` path.
    """

    registry_path = tmp_path / "app-local.md"
    registry_path.write_text(_CORRUPT_REGISTRY, encoding="utf-8")
    vault = tmp_path / "vault"

    result = _manager(tmp_path).initialize_vault(vault, remember=True)

    assert result.context.status == "selected"
    assert list(tmp_path.glob("app-local.md.corrupt-*"))
    reloaded = AppLocalSettingsStore(registry_path).load()
    assert reloaded.last_active_vault_ref in reloaded.known_vaults


def test_backup_corrupt_and_reset_noop_without_file(tmp_path: Path) -> None:
    """Backing up a missing registry is a no-op returning None."""

    store = AppLocalSettingsStore(tmp_path / "absent.md")

    assert store.backup_corrupt_and_reset() is None
