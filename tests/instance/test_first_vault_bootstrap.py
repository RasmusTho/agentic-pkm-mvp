from pathlib import Path

import pytest

from app.instance.first_vault_bootstrap import (
    BootstrapPreconditionError,
    FirstVaultBootstrapStore,
)
from app.instance.vault_registry import VaultRegistryStore


def test_first_vault_bootstrap_is_single_use_and_target_bound(tmp_path: Path) -> None:
    registry = VaultRegistryStore(tmp_path / "registry.md")
    target = tmp_path / "vault"
    store = FirstVaultBootstrapStore()
    token = store.issue(subject="trusted_loopback", target=target, registry=registry)

    store.consume(token=token, subject="trusted_loopback", target=target, registry=registry)
    with pytest.raises(BootstrapPreconditionError, match="invalid"):
        store.consume(token=token, subject="trusted_loopback", target=target, registry=registry)


def test_first_vault_bootstrap_rejects_other_target(tmp_path: Path) -> None:
    registry = VaultRegistryStore(tmp_path / "registry.md")
    store = FirstVaultBootstrapStore()
    token = store.issue(subject="trusted_loopback", target=tmp_path / "a", registry=registry)

    with pytest.raises(BootstrapPreconditionError, match="invalid"):
        store.consume(
            token=token,
            subject="trusted_loopback",
            target=tmp_path / "b",
            registry=registry,
        )
