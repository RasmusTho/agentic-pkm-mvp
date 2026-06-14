from __future__ import annotations

from app.vault.app_local import AppLocalSettingsStore, KnownVaultRef


def test_known_vault_registry_round_trips(tmp_path) -> None:
    store = AppLocalSettingsStore(tmp_path / "app-local.md")

    store.upsert_known_vault(KnownVaultRef(ref="path:/vaults/main", path="/vaults/main", vault_id="vault-1"))
    loaded = store.load()

    assert loaded.app_install_id.startswith("app-")
    assert loaded.last_active_vault_ref == "path:/vaults/main"
    assert loaded.known_vaults["path:/vaults/main"].vault_id == "vault-1"


def test_missing_known_vault_path_is_preserved_for_repair(tmp_path) -> None:
    store = AppLocalSettingsStore(tmp_path / "app-local.md")

    store.upsert_known_vault(KnownVaultRef(ref="path:/missing", path="/missing", vault_id="vault-1"))

    assert store.load().known_vaults["path:/missing"].path == "/missing"


def test_same_vault_id_at_multiple_paths_keeps_separate_refs(tmp_path) -> None:
    store = AppLocalSettingsStore(tmp_path / "app-local.md")

    store.upsert_known_vault(KnownVaultRef(ref="path:/vaults/main", path="/vaults/main", vault_id="same"))
    store.upsert_known_vault(KnownVaultRef(ref="path:/vaults/clone", path="/vaults/clone", vault_id="same"))
    loaded = store.load()

    assert sorted(loaded.known_vaults) == ["path:/vaults/clone", "path:/vaults/main"]
    assert loaded.known_vaults["path:/vaults/main"].path != loaded.known_vaults["path:/vaults/clone"].path
