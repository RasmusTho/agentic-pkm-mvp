from __future__ import annotations

import pytest

import app.instance.vault_registry as registry_module
from app.instance.filesystem_identity import FilesystemRootIdentity
from app.instance.vault_registry import RegistryMigrationError, VaultRegistryStore
from app.vault.markdown_settings import MarkdownSettingsStore


def _write_legacy(path, frontmatter) -> None:
    MarkdownSettingsStore().write_frontmatter(path, frontmatter, body="# Legacy app-local settings\n")


def test_legacy_app_local_state_migrates_losslessly(tmp_path) -> None:
    legacy_directory = tmp_path / "legacy-app-data"
    legacy_directory.mkdir(mode=0o755)
    legacy_directory.chmod(0o755)
    path = legacy_directory / "app-local.md"
    _write_legacy(
        path,
        {
            "schema": "design-handoff.app-local.v1",
            "scope": "app-local",
            "appInstallId": "app-stable",
            "lastActiveVaultRef": "path:/vault/a",
            "futureTopLevel": {"preserve": True},
            "knownVaults": {
                "path:/vault/a": {
                    "path": "/vault/a",
                    "vaultId": "vault-a",
                    "vaultName": "A",
                    "localInstanceId": "clone-a",
                    "lastOpenedAt": "2026-07-01T00:00:00Z",
                    "futureRegistration": "keep-me",
                }
            },
        },
    )
    path.chmod(0o644)

    migrated = VaultRegistryStore(path).load_or_migrate()
    registration = next(iter(migrated.registrations.values()))
    assert migrated.app_install_id == "app-stable"
    assert migrated.last_active_vault_ref == "path:/vault/a"
    assert migrated.extensions["futureTopLevel"] == {"preserve": True}
    assert registration.ref == "path:/vault/a"
    assert registration.vault_id == "vault-a"
    assert registration.local_instance_id == "clone-a"
    assert registration.last_opened_at == "2026-07-01T00:00:00Z"
    assert registration.extensions["futureRegistration"] == "keep-me"
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600


def test_settings_rebind_provisional_ids_are_adopted_atomically(tmp_path) -> None:
    path = tmp_path / "app-local.md"
    _write_legacy(
        path,
        {
            "schema": "design-handoff.app-local.v1",
            "appInstallId": "app-stable",
            "knownVaults": {
                "path:/vault/a": {"path": "/vault/a", "vaultId": "vault-a", "localInstanceId": "clone-a"}
            },
            "settingsRebind": {
                "schema": "settings_rebind.v1",
                "prior": {"ref": "path:/vault/a", "path": "/vault/a", "vaultBindingId": "provisional-a"},
                "candidate": {"ref": "path:/vault/a", "path": "/vault/a", "vaultBindingId": "provisional-a"},
                "applied": {"ref": "path:/vault/a", "path": "/vault/a", "vaultBindingId": "provisional-a"},
            },
        },
    )

    migrated = VaultRegistryStore(path).load_or_migrate()
    assert set(migrated.registrations) == {"provisional-a"}
    assert migrated.settings_rebind is not None
    for key in ("prior", "candidate", "applied"):
        assert migrated.settings_rebind[key]["vaultBindingId"] == "provisional-a"

    alias_path = tmp_path / "alias.md"
    _write_legacy(
        alias_path,
        {
            "schema": "design-handoff.app-local.v1",
            "appInstallId": "app-alias",
            "knownVaults": {
                "path:/vault/a": {"path": "/vault/a", "vaultId": "vault-a"},
                "alias:/vault/a": {"path": "/vault/../vault/a", "vaultId": "vault-a"},
            },
            "settingsRebind": {
                "schema": "settings_rebind.v1",
                "candidate": {
                    "ref": "alias:/vault/a",
                    "path": "/vault/../vault/a",
                    "vaultBindingId": "provisional-alias",
                },
            },
        },
    )
    alias_migration = VaultRegistryStore(alias_path).load_or_migrate()
    assert set(alias_migration.registrations) == {"provisional-alias"}
    assert alias_migration.settings_rebind["candidate"]["ref"] == "alias:/vault/a"

    physical_alias_path = tmp_path / "physical-alias.md"
    _write_legacy(
        physical_alias_path,
        {
            "schema": "design-handoff.app-local.v1",
            "appInstallId": "app-physical-alias",
            "lastActiveVaultRef": "mount:/b",
            "knownVaults": {
                "mount:/a": {"path": "/mount/a", "vaultId": "vault-a"},
                "mount:/b": {"path": "/mount/b", "vaultId": "vault-a"},
            },
            "settingsRebind": {
                "schema": "settings_rebind.v1",
                "candidate": {
                    "ref": "mount:/b",
                    "path": "/mount/b",
                    "vaultBindingId": "provisional-physical",
                },
            },
        },
    )
    real_resolver = registry_module.resolve_filesystem_root_identity

    def same_inode(value):
        identity = real_resolver(value)
        if str(value) in {"/mount/a", "/mount/b"}:
            return FilesystemRootIdentity(identity.canonical_path, 17, 29)
        return identity

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(registry_module, "resolve_filesystem_root_identity", same_inode)
        physical_alias = VaultRegistryStore(physical_alias_path).load_or_migrate()
    assert set(physical_alias.registrations) == {"provisional-physical"}
    assert physical_alias.registrations["provisional-physical"].ref == "mount:/b"


def test_ambiguous_registry_migration_fails_without_destructive_reset(tmp_path, monkeypatch) -> None:
    path = tmp_path / "app-local.md"
    _write_legacy(
        path,
        {
            "schema": "design-handoff.app-local.v1",
            "appInstallId": "app-stable",
            "knownVaults": {
                "path:/vault/a": {"path": "/vault/a", "vaultId": "vault-a"},
                "alias:/vault/a": {"path": "/vault/a", "vaultId": "conflicting-vault"},
            },
            "settingsRebind": {
                "schema": "settings_rebind.v1",
                "candidate": {"path": "/vault/a", "vaultBindingId": "provisional-a"},
            },
        },
    )
    original = path.read_bytes()

    with pytest.raises(RegistryMigrationError, match="conflicting alias metadata"):
        VaultRegistryStore(path).load_or_migrate()

    assert path.read_bytes() == original
    assert not path.with_suffix(path.suffix + ".last-good").exists()

    blank_ref_path = tmp_path / "blank-ref.md"
    _write_legacy(
        blank_ref_path,
        {
            "schema": "design-handoff.app-local.v1",
            "appInstallId": "app-blank-ref",
            "knownVaults": {" ": {"path": "/vault/blank"}},
        },
    )
    blank_ref_original = blank_ref_path.read_bytes()
    with pytest.raises(RegistryMigrationError, match="registration ref is blank"):
        VaultRegistryStore(blank_ref_path).load_or_migrate()
    assert blank_ref_path.read_bytes() == blank_ref_original
    assert not blank_ref_path.with_suffix(blank_ref_path.suffix + ".last-good").exists()

    write_failure_path = tmp_path / "write-failure.md"
    _write_legacy(
        write_failure_path,
        {
            "schema": "design-handoff.app-local.v1",
            "appInstallId": "app-write-failure",
            "knownVaults": {"path:/vault/b": {"path": "/vault/b"}},
        },
    )
    write_failure_original = write_failure_path.read_bytes()
    real_atomic_write = registry_module._atomic_private_write

    def fail_registry_replace(candidate, payload):
        if candidate == write_failure_path:
            raise OSError("injected migration replace failure")
        real_atomic_write(candidate, payload)

    monkeypatch.setattr(registry_module, "_atomic_private_write", fail_registry_replace)
    with pytest.raises(OSError, match="injected migration replace failure"):
        VaultRegistryStore(write_failure_path).load_or_migrate()
    assert write_failure_path.read_bytes() == write_failure_original
    assert not write_failure_path.with_suffix(write_failure_path.suffix + ".last-good").exists()

    late_failure_path = tmp_path / "late-write-failure.md"
    _write_legacy(
        late_failure_path,
        {
            "schema": "design-handoff.app-local.v1",
            "appInstallId": "app-late-write-failure",
            "knownVaults": {"path:/vault/c": {"path": "/vault/c"}},
        },
    )
    late_failure_original = late_failure_path.read_bytes()
    late_failure_store = VaultRegistryStore(late_failure_path)

    def fail_snapshot_replace(candidate, payload):
        if candidate == late_failure_store.snapshot_path:
            raise OSError("injected snapshot replace failure")
        real_atomic_write(candidate, payload)

    monkeypatch.setattr(registry_module, "_atomic_private_write", fail_snapshot_replace)
    with pytest.raises(OSError, match="injected snapshot replace failure"):
        late_failure_store.load_or_migrate()
    assert late_failure_path.read_bytes() == late_failure_original
    assert not late_failure_store.snapshot_path.exists()
    assert not late_failure_store.snapshot_checksum_path.exists()

    collision_path = tmp_path / "collision.md"
    collision_store = VaultRegistryStore(collision_path)
    collision_store.register(
        registry_module.VaultRegistration("binding-a", "path:/vault/a", "/vault/a")
    )
    collision_before = collision_path.read_bytes()
    with pytest.raises(registry_module.RegistryError, match="path identity collision"):
        collision_store.register(
            registry_module.VaultRegistration(
                "binding-alias",
                "path:/vault/alias",
                "/vault/../vault/a",
            )
        )
    assert collision_path.read_bytes() == collision_before
