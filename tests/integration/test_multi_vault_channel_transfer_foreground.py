"""MVR-05B foreground fence across a staged channel transfer."""

from pathlib import Path

import pytest

from app.instance.binding_effect_lease import BindingEffectLeaseManager
from app.instance.ownership_ledger import LedgerError, OwnershipLedger
from app.instance.vault_registry import VaultRegistration, VaultRegistryStore
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


def test_source_restart_cannot_read_after_staged_channel_lease_transfer(
    tmp_path: Path, monkeypatch
) -> None:
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

    _assert_migrated_companion_reads_fenced_after_transfer(tmp_path / "production", monkeypatch)


def _assert_migrated_companion_reads_fenced_after_transfer(tmp_path: Path, monkeypatch) -> None:
    """MVR-05B2: the same fence holds on the production companion read routes."""

    tmp_path.mkdir()

    from fastapi.testclient import TestClient

    import app.vault.manager as vault_manager_module
    from app.api.app import app
    from app.api.routes import active_context_selection as selection_routes
    from tests._mvr03_principal_harness import provisioned_instance

    runtime, first, _extra, _record = provisioned_instance(tmp_path)
    Path(first.path, "source.md").write_text("# Source", encoding="utf-8")
    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    selection_routes.reset_selection_store_for_tests()
    client = TestClient(app)
    selection = client.post(
        "/api/companion/active-context/selection",
        json={"vault_binding_ids": [first.vault_binding_id]},
    )
    assert selection.status_code == 201, selection.text
    headers = {"X-Active-Context-Session": selection.json()["context_selection_id"]}
    routes = ("/api/companion/vault/notes", "/api/companion/vault/context")
    for route in routes:
        before = client.get(route, headers=headers)
        assert before.status_code == 200, before.text

    runtime.ledger.begin_transfer(
        source_binding_id=first.vault_binding_id,
        destination_channel_id="destination",
        destination_binding_id="destination-binding",
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    runtime.ledger.activate_transfer(_capability=STORAGE_MUTATION_CAPABILITY)

    # Source restart: a fresh process-wide selector and client, but the stale
    # source registry and selection state are still present.
    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)
    restarted = TestClient(app)
    for route in routes:
        stale = restarted.get(route, headers=headers)
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"] == "active_context_read_unavailable"
        assert "source.md" not in stale.text
