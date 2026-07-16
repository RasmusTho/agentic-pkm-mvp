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
    assert not list(path.parent.glob(f".{path.name}.*"))

    path.chmod(0o644)
    with pytest.raises(RegistryError, match="unsafe registry mode"):
        preflight_registry_payload(path)

    unsafe_parent = tmp_path / "unsafe-state"
    unsafe_parent.mkdir(mode=0o755)
    unsafe_parent.chmod(0o755)
    with pytest.raises(RegistryError, match="unsafe registry mode"):
        VaultRegistryStore(unsafe_parent / "registry.md").load()
