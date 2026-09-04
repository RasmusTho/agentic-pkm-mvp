"""MVR-05B foreground fence across a staged channel transfer."""

from pathlib import Path

import pytest

from app.instance.binding_effect_lease import BindingEffectLeaseManager
from app.instance.ownership_ledger import LedgerError, OwnershipLedger
from app.instance.vault_registry import VaultRegistration, VaultRegistryStore
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


def test_source_restart_cannot_read_after_staged_channel_lease_transfer(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    registry = VaultRegistryStore(tmp_path / "instance" / "vault-registry.md")
    registry.register(
        VaultRegistration("source-binding", f"path:{root}", str(root)),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    ledger = OwnershipLedger(tmp_path / "owners")
    ledger.reserve(
        channel_id="source", vault_binding_id="source-binding", root=root,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    ledger.activate("source-binding", _capability=STORAGE_MUTATION_CAPABILITY)
    leases = BindingEffectLeaseManager(
        registry_store=registry,
        ownership_ledger=ledger,
        state_root=tmp_path / "instance" / "leases",
        capability=STORAGE_MUTATION_CAPABILITY,
    )

    ledger.begin_transfer(
        source_binding_id="source-binding",
        destination_channel_id="destination",
        destination_binding_id="destination-binding",
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    ledger.activate_transfer(_capability=STORAGE_MUTATION_CAPABILITY)

    # A restarted source still has its old registry/selection reference, but
    # cannot cross the current ownership fence into any foreground read.
    with pytest.raises(LedgerError, match="matching active ownership lease"):
        with leases.shared_effect("source-binding", channel_id="source", root=root, timeout=0.05):
            pytest.fail("stale source must not acquire a read effect lease")
