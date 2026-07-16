from __future__ import annotations

import pytest

from app.instance.vault_registry import RegistryError, VaultRegistration, VaultRegistryStore


def test_registry_round_trip_preserves_multiple_vaults(tmp_path) -> None:
    path = tmp_path / "instance-state" / "vault-registry.md"
    store = VaultRegistryStore(path)

    store.register(
        VaultRegistration(
            vault_binding_id="binding-a",
            ref="path:/vault/a",
            path="/vault/a",
            vault_id="logical-shared",
            local_instance_id="clone-a",
        )
    )
    store.register(
        VaultRegistration(
            vault_binding_id="binding-b",
            ref="path:/vault/b",
            path="/vault/b",
            vault_id="logical-shared",
            local_instance_id="clone-b",
        )
    )

    assert [item.vault_binding_id for item in store.list_registrations()] == ["binding-a", "binding-b"]
    assert store.lookup("binding-a") is not None
    updated = store.update_registration(
        VaultRegistration(
            vault_binding_id="binding-a",
            ref="path:/moved/a",
            path="/moved/a",
            vault_id="logical-shared",
            local_instance_id="clone-a",
        ),
        expected_revision=2,
    )
    assert updated.revision == 3

    with pytest.raises(RegistryError, match="stable registration identity cannot change"):
        store.update_registration(
            VaultRegistration(
                vault_binding_id="binding-a",
                ref="path:/moved/a",
                path="/moved/a",
                vault_id="logical-shared",
                local_instance_id="different-clone",
            ),
            expected_revision=3,
        )
    assert store.load().revision == 3

    store.register(VaultRegistration("binding-temporary", "path:/temporary", "/temporary"))
    store.remove_registration("binding-temporary", expected_revision=4)

    reloaded = VaultRegistryStore(path).load()
    assert reloaded.authority == "dormant"
    assert reloaded.revision == 5
    assert set(reloaded.registrations) == {"binding-a", "binding-b"}
    assert reloaded.registrations["binding-a"].vault_id == "logical-shared"
    assert reloaded.registrations["binding-a"].path == "/moved/a"
    assert reloaded.registrations["binding-a"].local_instance_id == "clone-a"
    assert reloaded.registrations["binding-b"].local_instance_id == "clone-b"
