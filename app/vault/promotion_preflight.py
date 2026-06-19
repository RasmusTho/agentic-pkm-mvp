"""Promotion preflight for vault-settings readiness.

A vault that predates the vault-settings foundation (the five
``REQUIRED_SETTINGS_FILES`` in :mod:`app.vault.manager`) validates as
``uninitialized`` and the watcher fail-exits on startup. Promotion to such a
vault must initialize it first. This helper lets ``prepare-promotion`` surface
that as an explicit pre-check + remedy instead of discovering it as a prod
startup failure (issue #1991).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.vault.manager import VaultManager


@dataclass(frozen=True)
class VaultSettingsPreflight:
    """Result of checking whether a vault is initialized enough to promote into."""

    vault_path: str
    status: str
    initialized: bool
    blocking: bool
    detail: str
    remedy: str | None


def vault_settings_preflight(vault_path: Path | str) -> VaultSettingsPreflight:
    """Check whether ``vault_path`` is initialized for the vault-settings foundation.

    ``blocking`` is True when promotion would fail to start against this vault.
    For an ``uninitialized`` vault the remedy is the ``vault init`` command; for a
    ``missing``/``invalid`` vault the path/config itself must be fixed first.
    """

    path = Path(vault_path).expanduser()
    manager = VaultManager()
    context = manager.validate_vault(path)
    status = context.status
    detail = context.validation_error or ""
    initialized = status == "selected"
    remedy: str | None = None
    blocking = not initialized
    if status == "uninitialized":
        remedy = f"python -m app.cli vault init --path {path}"
    elif initialized and not manager.permissions_for_context(context).enable_vault_watcher:
        # A `selected` vault whose settings/local.md disables the watcher still
        # fail-exits the runtime at startup (app/watcher/config.py:92-93), so
        # prepare-promotion must treat it as blocking rather than green-lighting a
        # vault that cannot boot. Distinct from `uninitialized`: the settings exist
        # but disable the watcher, so the remedy is the settings file, not init.
        blocking = True
        detail = detail or "settings/local.md disables the vault watcher (enableVaultWatcher: false)"
        remedy = f"set enableVaultWatcher: true in {path / 'settings' / 'local.md'}"
    return VaultSettingsPreflight(
        vault_path=str(path),
        status=status,
        initialized=initialized,
        blocking=blocking,
        detail=detail,
        remedy=remedy,
    )


__all__ = ["VaultSettingsPreflight", "vault_settings_preflight"]
