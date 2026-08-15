from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from app.instance.vault_registry import RegistryError, VaultRegistration, VaultRegistryStore
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


def _valid_lease_state(binding_id: str) -> dict[str, object]:
    return {
        "schema": "agentic-pkm.binding-effect-lease.v1",
        "vaultBindingId": binding_id,
        "generation": 1,
        "nextTicket": 2,
        "sharedHolders": [],
        "exclusivePending": [],
        "exclusiveHolder": None,
    }


def test_lease_state_has_its_own_validated_producer(tmp_path) -> None:
    store = VaultRegistryStore(tmp_path / "vault-registry.md")
    registration = VaultRegistration("binding-a", "path:/vault/a", "/vault/a")
    registered = store.register(
        registration,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    valid = _valid_lease_state("binding-a")
    updated = store.set_binding_effect_lease_state(
        "binding-a",
        valid,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    assert updated.extensions["bindingEffectLeases"]["binding-a"] == valid
    assert updated.revision == registered.revision

    lifecycle_update = store.update_registration(
        registration,
        expected_revision=registered.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    assert lifecycle_update.revision == registered.revision + 1
    assert lifecycle_update.extensions["bindingEffectLeases"]["binding-a"] == valid

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


def test_lease_state_preserves_active_scalar_rollback_authority(tmp_path) -> None:
    store = VaultRegistryStore(tmp_path / "vault-registry.md")
    registration = VaultRegistration("binding-a", "path:/vault/a", "/vault/a")
    registered = store.register(
        registration,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    extensions = copy.deepcopy(registered.extensions)
    extensions["scalarRollback"] = {
        "schema": "agentic-pkm.scalar-rollback-floor.v1",
        "targetVaultBindingId": registration.vault_binding_id,
        "targetRef": registration.ref,
        "targetPath": registration.path,
        "forkRegistryRevision": registered.revision,
        "gatewayPreflight": "authenticated-mutation-filter",
        "nativeGuardPreflight": "deny-by-default",
        "rollForwardLineage": "agentic-pkm.scalar-roll-forward-lineage.v1",
        "composePolicySha256": "a" * 64,
        "gatewayPolicySha256": "b" * 64,
        "nativeLauncherSha256": "c" * 64,
    }
    active = replace(registered, authority="active", extensions=extensions)
    with store._locked():
        store._write_locked(active)

    updated = store.set_binding_effect_lease_state(
        registration.vault_binding_id,
        _valid_lease_state(registration.vault_binding_id),
        expected_revision=active.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    reloaded = store.load()

    assert updated.revision == active.revision
    assert updated.extensions["scalarRollback"] == active.extensions["scalarRollback"]
    assert reloaded == updated
