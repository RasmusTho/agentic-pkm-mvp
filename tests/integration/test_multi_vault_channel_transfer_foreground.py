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


def test_source_restart_cannot_write_after_channel_lease_transfer(tmp_path, monkeypatch):
    from tests._mvr05c_transfer_harness import transfer_pair, reopen
    from app.instance.channel_transfer import require_source_ingress
    source, destination, original, lifecycle = transfer_pair(tmp_path, monkeypatch)
    target = source.transfer_to(destination, original.vault_binding_id, stop_and_prove=lifecycle)
    source = reopen(source)
    with pytest.raises(RuntimeError, match="ingress is closed"):
        require_source_ingress(source.registry, original.vault_binding_id)
    leases = BindingEffectLeaseManager.for_runtime(registry_store=source.registry, ownership_root=source.ledger.root,
        state_root=source.layout.root / "binding-effect-leases")
    with pytest.raises(LedgerError):
        with leases.shared_effect(original.vault_binding_id, channel_id=source.layout.channel_id, root=Path(original.path)):
            pytest.fail("stale source writer acquired authority")
    assert target != original.vault_binding_id


def test_destination_uses_minted_binding_and_transfer_lineage(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.api.app import app
    from app.api.routes import active_context_selection as selections
    from app.api.routes import capture
    from tests._mvr05c_transfer_harness import transfer_pair
    source, destination, original, lifecycle = transfer_pair(tmp_path, monkeypatch)
    target = source.transfer_to(destination, original.vault_binding_id, stop_and_prove=lifecycle)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(destination.registry.path))
    monkeypatch.setenv("PKM_ENVIRONMENT", destination.layout.channel_id)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "destination-events.jsonl"))
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    monkeypatch.setattr(capture, "_offer_question_registration_proposal", lambda **_: None)
    selections.reset_selection_store_for_tests()
    client = TestClient(app)
    old = client.post("/api/companion/active-context/selection", json={"vault_binding_ids": [original.vault_binding_id]})
    assert old.status_code in (403, 404, 409), old.text
    selected = client.post("/api/companion/active-context/selection", json={"vault_binding_ids": [target]})
    assert selected.status_code == 201, selected.text
    headers = {"X-Active-Context-Session": selected.json()["context_selection_id"]}
    written = client.post("/api/companion/capture/scoped", headers=headers, json={"text": "Destination capture", "target_binding_id": target})
    assert written.status_code == 200, written.text
    assert written.json()["governed_write"]["authority_receipt"]["target_binding_id"] == target
    assert destination.registry.load().transfer_lineage[-1].source_binding_id == original.vault_binding_id


@pytest.mark.parametrize("stage", ["ingress_closed", "complete"])
def test_source_cli_cannot_mutate_retiring_root(tmp_path, monkeypatch, stage):
    from click.testing import CliRunner
    from app.cli import cli
    from app.instance import channel_transfer
    from tests._mvr05c_transfer_harness import transfer_pair, reopen
    source, destination, original, stop = transfer_pair(tmp_path, monkeypatch)
    class Crash(BaseException):
        pass
    def crash(phase):
        if phase == stage:
            raise Crash()
    monkeypatch.setattr(channel_transfer, "_fault_point", crash)
    with pytest.raises(Crash):
        source.transfer_to(destination, original.vault_binding_id, stop_and_prove=stop)
    # Exercise the real Click producer after reconstructing source state.
    source = reopen(source)
    before = {str(p.relative_to(original.path)): p.read_bytes() for p in Path(original.path).rglob("*") if p.is_file()}
    result = CliRunner().invoke(cli, ["canvas", "open", "note.md", "--vault-root", original.path])
    assert result.exit_code != 0
    assert "source binding ingress is closed" in result.output
    after = {str(p.relative_to(original.path)): p.read_bytes() for p in Path(original.path).rglob("*") if p.is_file()}
    assert before == after


def test_cached_filesystem_port_cannot_bypass_retired_source_admission(tmp_path, monkeypatch):
    from app.knowledge.adapters import FsVaultAdapter
    from app.knowledge.locators import make_note_locator
    from tests._mvr05c_transfer_harness import transfer_pair
    source, destination, original, stop = transfer_pair(tmp_path, monkeypatch)
    cached = FsVaultAdapter(original.path)
    source.transfer_to(destination, original.vault_binding_id, stop_and_prove=stop)
    with pytest.raises(RuntimeError, match="source binding ingress is closed"):
        cached.write_note(make_note_locator("forbidden.md"), "source must not write")
    assert not Path(original.path, "forbidden.md").exists()


def test_real_channel_startup_refuses_retired_source_and_admits_destination(tmp_path, monkeypatch):
    from app.instance.runtime import _preflight_runtime
    from tests._mvr05c_transfer_harness import transfer_pair
    source, destination, original, stop = transfer_pair(tmp_path, monkeypatch)
    target = source.transfer_to(destination, original.vault_binding_id, stop_and_prove=stop)
    monkeypatch.setenv("VAULT_ROOT", original.path)
    monkeypatch.setenv("WATCHER_VAULT_PATH", original.path)
    with pytest.raises(RuntimeError, match="restart-fenced"):
        _preflight_runtime(channel=source.layout.channel_id, instance_state_root=source.layout.root.parent,
            host_global_root=source.ledger.root, consumer="api")
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(destination.registry.path))
    monkeypatch.setenv("PKM_ENVIRONMENT", destination.layout.channel_id)
    assert _preflight_runtime(channel=destination.layout.channel_id, instance_state_root=destination.layout.root.parent,
        host_global_root=destination.ledger.root, consumer="api") == 0
    assert destination.registry.lookup(target).local_instance_id == original.local_instance_id


@pytest.mark.parametrize("registry_state", ["missing-fresh", "missing-established"])
@pytest.mark.parametrize("operation", ["read", "write"])
def test_cached_filesystem_port_refuses_missing_authority_without_registry_repair(
    tmp_path, monkeypatch, registry_state, operation,
):
    from app.knowledge.adapters import FsVaultAdapter
    from app.knowledge.locators import make_note_locator
    from tests._mvr05c_transfer_harness import transfer_pair

    source, destination, original, stop = transfer_pair(tmp_path, monkeypatch)
    (Path(original.path) / "source.md").write_text("retained source bytes\n")
    cached = FsVaultAdapter(original.path)
    source.transfer_to(destination, original.vault_binding_id, stop_and_prove=stop)
    if registry_state == "missing-established":
        registry = source.registry.path
        registry.unlink()  # Last-good recovery is not an admission capability.
    else:
        private = tmp_path / "unprovisioned-source"
        private.mkdir(mode=0o700)
        registry = private / "registry.md"
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(registry))
    before = {p.relative_to(registry.parent): p.read_bytes()
              for p in registry.parent.rglob("*") if p.is_file()}
    with pytest.raises(RuntimeError, match="required registry path is missing"):
        if operation == "read":
            cached.read_note(make_note_locator("source.md"))
        else:
            cached.write_note(make_note_locator("forbidden.md"), "must not write")
    assert not registry.exists()
    assert {p.relative_to(registry.parent): p.read_bytes()
            for p in registry.parent.rglob("*") if p.is_file()} == before
    assert (Path(original.path) / "source.md").read_text() == "retained source bytes\n"
    assert not Path(original.path, "forbidden.md").exists()
