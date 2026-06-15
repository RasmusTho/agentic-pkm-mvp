from __future__ import annotations

from pathlib import Path

import pytest

from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager

pytestmark = pytest.mark.not_pg


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_vault_missing_vault_id(vault_root: Path, *, machine_role: str) -> Path:
    settings_dir = vault_root / "settings"
    _write(
        settings_dir / "vault.md",
        "---\nschema: design-handoff.vault.v1\nscope: vault-shared\nvaultName: Test\n---\n# Vault\n",
    )  # deliberately no vaultId
    _write(
        settings_dir / "paths.md",
        "---\nscope: vault-shared\nhandoffFolder: Design Handoff\n---\n",
    )
    for name in ("workflow.md", "design-handoff.md", "companion-ui.md"):
        _write(settings_dir / name, "---\nscope: vault-shared\n---\n")
    _write(
        settings_dir / "local.md",
        "---\nschema: design-handoff.local.v1\nscope: vault-local\n"
        f"localInstanceId: l1\nmachineRole: {machine_role}\n---\n# Local\n",
    )
    return settings_dir


def test_vaultid_heal_honors_readonly_role(tmp_path: Path) -> None:
    """A missing ``vaultId`` must NOT be healed (which writes the shared settings
    file) for a read-only role; the vault still resolves with a runtime-only id."""
    vault_root = tmp_path / "vault"
    settings_dir = _init_vault_missing_vault_id(vault_root, machine_role="readOnlySatellite")
    vault_md = settings_dir / "vault.md"
    before = vault_md.read_text(encoding="utf-8")

    manager = VaultManager(app_local_store=AppLocalSettingsStore(path=tmp_path / "app-local.md"))
    context = manager.validate_vault(vault_root)

    # The vault must still be usable.
    assert context.status == "selected"
    assert context.machine_role == "readOnlySatellite"
    assert context.active_vault_id  # a runtime id is provided
    # But the shared file on disk must be untouched (no write by a read-only role).
    after = vault_md.read_text(encoding="utf-8")
    assert after == before
    assert "vaultId" not in after


def test_vaultid_heal_runs_for_primary_role(tmp_path: Path) -> None:
    """Regression guard: the heal still persists vaultId for a writable role."""
    vault_root = tmp_path / "vault"
    settings_dir = _init_vault_missing_vault_id(vault_root, machine_role="primary")
    vault_md = settings_dir / "vault.md"

    manager = VaultManager(app_local_store=AppLocalSettingsStore(path=tmp_path / "app-local.md"))
    context = manager.validate_vault(vault_root)

    assert context.status == "selected"
    assert "vaultId" in vault_md.read_text(encoding="utf-8")


def test_local_instance_id_heal_persists_for_satellite(tmp_path: Path) -> None:
    """A satellite (shared edits disabled by default) with a missing
    localInstanceId must still persist it to the gitignored local.md, so local
    clone identity stays stable across loads (Codex #2030 P2)."""
    vault_root = tmp_path / "vault"
    settings_dir = _init_vault_missing_vault_id(vault_root, machine_role="satellite")
    # Remove localInstanceId so only the local id is missing.
    local_md = settings_dir / "local.md"
    local_md.write_text(
        "---\nschema: design-handoff.local.v1\nscope: vault-local\nmachineRole: satellite\n---\n# Local\n",
        encoding="utf-8",
    )
    vault_md = settings_dir / "vault.md"
    vault_before = vault_md.read_text(encoding="utf-8")

    manager = VaultManager(app_local_store=AppLocalSettingsStore(path=tmp_path / "app-local.md"))
    first = manager.validate_vault(vault_root)
    second = manager.validate_vault(vault_root)

    assert first.status == "selected"
    # localInstanceId persisted to the local file -> stable across loads.
    assert "localInstanceId" in local_md.read_text(encoding="utf-8")
    assert first.local_instance_id == second.local_instance_id
    # vaultId is shared; a satellite with shared edits disabled must NOT write vault.md.
    assert vault_md.read_text(encoding="utf-8") == vault_before
    assert "vaultId" not in vault_md.read_text(encoding="utf-8")


def test_local_instance_id_heal_skipped_for_readonly(tmp_path: Path) -> None:
    """The read-only ceiling still blocks even the local.md write."""
    vault_root = tmp_path / "vault"
    settings_dir = _init_vault_missing_vault_id(vault_root, machine_role="readOnlySatellite")
    local_md = settings_dir / "local.md"
    local_md.write_text(
        "---\nschema: design-handoff.local.v1\nscope: vault-local\nmachineRole: readOnlySatellite\n---\n# Local\n",
        encoding="utf-8",
    )
    before = local_md.read_text(encoding="utf-8")

    manager = VaultManager(app_local_store=AppLocalSettingsStore(path=tmp_path / "app-local.md"))
    context = manager.validate_vault(vault_root)

    assert context.status == "selected"
    assert context.local_instance_id  # runtime id still provided
    assert local_md.read_text(encoding="utf-8") == before
    assert "localInstanceId" not in local_md.read_text(encoding="utf-8")
