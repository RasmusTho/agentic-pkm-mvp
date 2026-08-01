from __future__ import annotations

import pytest

from app.instance.vault_registry import RegistryError, VaultRegistration, VaultRegistryStore
from app.vault.manager import VaultManager
from app.vault.markdown_settings import MarkdownSettingsStore
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


def test_picker_recovers_parse_corrupt_registry_with_backup(tmp_path) -> None:
    vault = tmp_path / "vault"
    legacy_path = tmp_path / "app-local.md"
    manager = VaultManager()
    manager.app_local_store.path = legacy_path
    manager.initialize_vault(vault, remember=False)
    legacy_path.write_text("---\n<<<<<<< HEAD\nappInstallId: a\n=======\nappInstallId: b\n>>>>>>> branch\n---\n")

    context = manager.select_vault(vault, remember=True)

    assert context.status == "selected"
    assert list(tmp_path.glob("app-local.md.corrupt-*"))

    initialize_path = tmp_path / "initialize-app-local.md"
    initialize_path.write_text("---\n<<<<<<< HEAD\nappInstallId: a\n=======\nappInstallId: b\n>>>>>>> branch\n---\n")
    initialize_manager = VaultManager()
    initialize_manager.app_local_store.path = initialize_path
    result = initialize_manager.initialize_vault(tmp_path / "initialized-vault", remember=True)
    assert result.context.status == "selected"
    assert list(tmp_path.glob("initialize-app-local.md.corrupt-*"))


def test_populated_registry_corruption_never_reseeds_empty(tmp_path) -> None:
    path = tmp_path / "vault-registry.md"
    MarkdownSettingsStore().write_frontmatter(
        path,
        {
            "schema": "design-handoff.app-local.v1",
            "appInstallId": "app-recovery",
            "knownVaults": {
                "path:/a": {"path": "/a", "vaultId": "vault-a", "localInstanceId": "clone-a"},
                "path:/b": {"path": "/b", "vaultId": "vault-b", "localInstanceId": "clone-b"},
            },
            "defaultVaultBindingId": "future-default",
            "dimensions": {"focus": ["future-default"]},
            "backgroundIntent": {"mode": "explicit"},
        },
    )
    store = VaultRegistryStore(path)
    migrated = store.load_or_migrate()
    path.write_text("---\nnot: [valid\n---\n", encoding="utf-8")

    recovered = VaultRegistryStore(path).load()

    assert recovered.revision == migrated.revision
    assert len(recovered.registrations) == 2
    # MVR-02 owns ``defaultVaultBindingId`` as a validated registry field. A legacy
    # value that names no migrated registration is never adopted (that would be a
    # dangling default) and is never silently dropped either: it survives as lineage.
    assert recovered.default_vault_binding_id is None
    assert recovered.extensions["legacyDefaultVaultBindingId"] == "future-default"
    assert recovered.extensions["dimensions"] == {"focus": ["future-default"]}
    assert recovered.extensions["backgroundIntent"] == {"mode": "explicit"}

    path.unlink()
    restored_missing_main = VaultRegistryStore(path).load()
    assert restored_missing_main.revision == recovered.revision
    assert set(restored_missing_main.registrations) == set(recovered.registrations)

    path.unlink()
    migrated_missing_main = VaultRegistryStore(path).load_or_migrate()
    assert migrated_missing_main.revision == recovered.revision
    assert set(migrated_missing_main.registrations) == set(recovered.registrations)

    path.unlink()
    mutated_missing_main = VaultRegistryStore(path).register(
        VaultRegistration("binding-c", "path:/c", "/c"),
        expected_revision=recovered.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    assert mutated_missing_main.revision == recovered.revision + 1
    assert len(mutated_missing_main.registrations) == 3

    no_snapshot_path = tmp_path / "no-snapshot.md"
    no_snapshot_store = VaultRegistryStore(no_snapshot_path)
    no_snapshot_store.load()
    no_snapshot_store.snapshot_path.unlink()
    no_snapshot_store.snapshot_checksum_path.unlink()
    corrupt_payload = "---\nnot: [valid\n---\n"
    no_snapshot_path.write_text(corrupt_payload, encoding="utf-8")
    with pytest.raises(RegistryError, match="no unambiguous last-good snapshot"):
        no_snapshot_store.load()
    assert no_snapshot_path.read_text(encoding="utf-8") == corrupt_payload
    assert not no_snapshot_store.snapshot_path.exists()
