from __future__ import annotations

import os

import pytest

from app.instance.vault_registry import RegistryError, VaultRegistration, VaultRegistryStore, preflight_registry_payload


def test_registry_transaction_files_are_private(tmp_path) -> None:
    path = tmp_path / "state" / "vault-registry.md"
    previous_umask = os.umask(0)
    try:
        store = VaultRegistryStore(path)
        store.register(VaultRegistration("binding-a", "path:/a", "/a"))
    finally:
        os.umask(previous_umask)

    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert store.lock_path.stat().st_mode & 0o777 == 0o600
    assert store.snapshot_path.stat().st_mode & 0o777 == 0o600
    assert store.snapshot_checksum_path.stat().st_mode & 0o777 == 0o600
    assert not store.transaction_path.exists()
    assert not list(path.parent.glob(f".{path.name}.*"))

    path.chmod(0o644)
    with pytest.raises(RegistryError, match="unsafe registry mode"):
        preflight_registry_payload(path)
    with pytest.raises(RegistryError, match="unsafe registry mode"):
        store.load_or_migrate()

    path.chmod(0o600)
    symlink_path = path.parent / "registry-link.md"
    symlink_path.symlink_to(path.name)
    with pytest.raises(RegistryError, match="unsafe legacy registry source|unsafe registry path type"):
        preflight_registry_payload(symlink_path)

    unsafe_parent = tmp_path / "unsafe-state"
    unsafe_parent.mkdir(mode=0o755)
    unsafe_parent.chmod(0o755)
    with pytest.raises(RegistryError, match="unsafe registry mode"):
        VaultRegistryStore(unsafe_parent / "registry.md").load()


def test_registry_write_rejects_symlinked_snapshot_without_mutating_state(tmp_path) -> None:
    path = tmp_path / "state" / "vault-registry.md"
    store = VaultRegistryStore(path)
    initial = store.register(VaultRegistration("binding-a", "path:/a", "/a"))
    external = tmp_path / "external.md"
    external.write_text("do not overwrite\n", encoding="utf-8")
    store.snapshot_path.unlink()
    store.snapshot_path.symlink_to(external)

    with pytest.raises(RegistryError, match="unsafe registry transaction path"):
        store.register(VaultRegistration("binding-b", "path:/b", "/b"))

    assert external.read_text(encoding="utf-8") == "do not overwrite\n"
    assert store.load().revision == initial.revision

    transaction_target = tmp_path / "transaction-target.json"
    transaction_target.write_text("do not parse\n", encoding="utf-8")
    store.transaction_path.symlink_to(transaction_target)
    with pytest.raises(RegistryError, match="unsafe registry path type"):
        store.load()
    assert transaction_target.read_text(encoding="utf-8") == "do not parse\n"
