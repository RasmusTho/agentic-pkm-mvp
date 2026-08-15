from __future__ import annotations

import pytest

from app.instance.vault_registry import RegistryError, VaultRegistration, VaultRegistryStore
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


def test_lease_state_has_its_own_validated_producer(tmp_path) -> None:
    store = VaultRegistryStore(tmp_path / "vault-registry.md")
    store.register(
        VaultRegistration("binding-a", "path:/vault/a", "/vault/a"),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    valid = {
        "schema": "agentic-pkm.binding-effect-lease.v1",
        "vaultBindingId": "binding-a",
        "generation": 1,
        "nextTicket": 2,
        "sharedHolders": [],
        "exclusivePending": [],
        "exclusiveHolder": None,
    }
    updated = store.set_binding_effect_lease_state(
        "binding-a",
        valid,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    assert updated.extensions["bindingEffectLeases"]["binding-a"] == valid

    with pytest.raises(RegistryError, match="binding effect lease state"):
        store.set_binding_effect_lease_state(
            "binding-a",
            {**valid, "sharedHolders": [{"pid": "not-an-int"}]},
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
    assert store.load().extensions["bindingEffectLeases"]["binding-a"] == valid

    with pytest.raises(TypeError):
        store.set_extension_state(  # type: ignore[call-arg]
            principal_state={},
            background_state={},
            runtime_floors={},
            binding_effect_leases={},
            _capability=STORAGE_MUTATION_CAPABILITY,
        )

    with pytest.raises(RegistryError, match="unknown binding"):
        store.remove_registration(
            "binding-a",
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
    assert "binding-a" in store.load().registrations
