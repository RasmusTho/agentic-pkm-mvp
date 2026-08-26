from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from app.events.models import new_event
from app.instance import mvr05_cutover as mvr05_cutover_module
from app.instance import ownership_ledger as ownership_ledger_module
from app.instance import runtime as runtime_module
from app.instance.instance_state import InstanceStateLayout
from app.instance.filesystem_identity import resolve_filesystem_root_identity
from app.instance.local_operator_principal import (
    LocalOperatorPrincipalStore,
    PROVENANCE_FRESH_BOOTSTRAP,
    SUBJECT_LOOPBACK,
)
from app.instance.mvr05_cutover import (
    Mvr05CutoverError,
    discover_db_producer_fence,
)
from app.instance.ownership_ledger import (
    LegacyOwner,
    LedgerError,
    LedgerKeyError,
    OwnershipLedger,
)
from app.instance.vault_registry import VaultRegistration, VaultRegistryStore
from app.services import outbox
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
from tests.helpers.mvr01c_authority import establish_authority_window, finish_authority_window


REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.not_pg


def _active_runtime(tmp_path: Path, monkeypatch) -> tuple[VaultRegistryStore, Path]:
    root = tmp_path / "vault"
    root.mkdir()
    registry = VaultRegistryStore(tmp_path / "instance" / "vault-registry.md")
    registered = registry.register(
        VaultRegistration("binding-a", f"path:{root}", str(root)),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    extensions = dict(registered.extensions)
    extensions["scalarRollback"] = {
        "schema": "agentic-pkm.scalar-rollback-floor.v1",
        "targetVaultBindingId": "binding-a",
        "targetRef": f"path:{root}",
        "targetPath": str(root),
        "forkRegistryRevision": registered.revision,
        "gatewayPreflight": "authenticated-mutation-filter",
        "nativeGuardPreflight": "deny-by-default",
        "rollForwardLineage": "agentic-pkm.scalar-roll-forward-lineage.v1",
        "composePolicySha256": "a" * 64,
        "gatewayPolicySha256": "b" * 64,
        "nativeLauncherSha256": "c" * 64,
    }
    with registry._locked():
        registry._write_locked(
            replace(registered, authority="active", extensions=extensions)
        )
    LocalOperatorPrincipalStore(
        registry.path.parent / "local-operator-principal.json"
    ).bootstrap(
        credential=None,
        subjects=(SUBJECT_LOOPBACK,),
        migration_provenance=PROVENANCE_FRESH_BOOTSTRAP,
        floor_guard=lambda: True,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    ledger = OwnershipLedger(tmp_path / "host-global")
    ledger.reserve(
        channel_id="dev",
        vault_binding_id="binding-a",
        root=root,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    ledger.activate("binding-a", _capability=STORAGE_MUTATION_CAPABILITY)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(registry.path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(ledger.root))
    monkeypatch.setenv("VAULT_ROOT", str(root))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    return registry, root


def test_all_old_scalar_db_clients_are_stopped_before_binding_keyed_migration() -> None:
    plan = discover_db_producer_fence(REPO_ROOT / "docker-compose.yaml")
    deployment = (REPO_ROOT / "scripts/lib/instance_state_deployment.sh").read_text()
    floor_marker = "python -m app.instance.runtime mvr05-record-floor"
    migration = (REPO_ROOT / "scripts/deploy_channel.sh").read_text()

    assert plan.migration_runner == "migrate"
    assert set(plan.stopped_services) == {
        "api",
        "worker",
        "watcher",
        "heimdal-capture-watch",
    }
    assert 'compose-fence-plan' in deployment
    assert 'stop "${mvr05_stop_service_args[@]}"' in deployment
    assert 'DEPLOY_COMPOSE_FENCE_CONFIG_OUTPUT="${mvr05_effective_compose_path}"' in deployment
    assert "redact-compose-fence-config" in (
        REPO_ROOT / "scripts/lib/deploy_channel_compose.sh"
    ).read_text()
    assert deployment.index(floor_marker) < deployment.rindex("deployment-finish")
    assert migration.rindex("prepare_instance_state_deployment") < migration.rindex(
        "apply_changed_migrations"
    )
    assert "target_sha}:app/instance/mvr05_cutover.py" in migration
    assert "target_sha}:app/instance/runtime.py" not in migration


def _floor_command(tmp_path, monkeypatch) -> tuple[list[str], Path, Path]:
    registry_path = tmp_path / "instance-state" / "agentic-pkm" / "vault-registry.md"
    host_global_root = tmp_path / "host-global"
    registry_path.parent.mkdir(parents=True, mode=0o700)
    host_global_root.mkdir(mode=0o700)
    proof_path = tmp_path / "quiescence-proof.json"
    proof_path.write_text(json.dumps({"nonce": "fresh-deployment"}), encoding="utf-8")
    fence_path = tmp_path / "mvr05-fence-plan.json"
    fence_path.write_text(
        json.dumps(discover_db_producer_fence(REPO_ROOT / "docker-compose.yaml").as_payload()),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_module,
        "_require_proved_deployment_lease",
        lambda **_kwargs: None,
    )
    return (
        [
            "mvr05-record-floor",
            "--channel",
            "dev",
            "--registry-path",
            str(registry_path),
            "--host-global-root",
            str(host_global_root),
            "--quiescence-proof-path",
            str(proof_path),
            "--fence-plan",
            str(fence_path),
        ],
        registry_path,
        host_global_root,
    )


def test_floor_producer_seeds_protected_ledger_before_first_registry_write(
    tmp_path, monkeypatch
) -> None:
    """A fresh host must not look like an established registry with lost authority."""

    command, registry_path, host_global_root = _floor_command(tmp_path, monkeypatch)
    record_floor = mvr05_cutover_module.record_mvr05_runtime_floor

    def record_floor_after_ledger(*args, **kwargs):
        OwnershipLedger(host_global_root).require_existing()
        return record_floor(*args, **kwargs)

    monkeypatch.setattr(
        mvr05_cutover_module,
        "record_mvr05_runtime_floor",
        record_floor_after_ledger,
    )

    assert runtime_module.main(command) == 0

    ledger = OwnershipLedger(host_global_root).require_existing()
    assert ledger.legacy_bootstrap_complete is False
    assert VaultRegistryStore(registry_path).load().revision == 1


def test_floor_producer_holds_stopped_window_through_floor_commit(
    tmp_path, monkeypatch
) -> None:
    command, registry_path, host_global_root = _floor_command(tmp_path, monkeypatch)
    record_started = threading.Event()
    admission_acquired = threading.Event()
    producer_acquired = threading.Event()
    record_floor = mvr05_cutover_module.record_mvr05_runtime_floor
    layout = runtime_module.InstanceStateLayout(
        root=registry_path.parent,
        channel_id="dev",
        registry_path=registry_path,
    )

    def competing_release() -> None:
        assert record_started.wait(timeout=1)
        with runtime_module._deployment_admission_locked(host_global_root):
            admission_acquired.set()

    def competing_producer() -> None:
        assert record_started.wait(timeout=1)
        with runtime_module._producer_transition_locked(layout):
            producer_acquired.set()

    def record_while_stopped(*args, **kwargs):
        record_started.set()
        assert not admission_acquired.wait(timeout=0.1)
        assert not producer_acquired.wait(timeout=0.1)
        return record_floor(*args, **kwargs)

    monkeypatch.setattr(
        mvr05_cutover_module,
        "record_mvr05_runtime_floor",
        record_while_stopped,
    )
    competitor = threading.Thread(target=competing_release)
    producer = threading.Thread(target=competing_producer)
    competitor.start()
    producer.start()

    assert runtime_module.main(command) == 0
    competitor.join(timeout=1)
    producer.join(timeout=1)

    assert not competitor.is_alive()
    assert not producer.is_alive()
    assert admission_acquired.is_set()
    assert producer_acquired.is_set()


def test_floor_producer_preserves_established_ledger_identity(tmp_path, monkeypatch) -> None:
    command, registry_path, host_global_root = _floor_command(tmp_path, monkeypatch)
    assert runtime_module.main(command) == 0
    before = OwnershipLedger(host_global_root).require_existing()

    assert runtime_module.main(command) == 0

    after = OwnershipLedger(host_global_root).require_existing()
    assert (after.key_id, after.generation) == (before.key_id, before.generation)
    assert VaultRegistryStore(registry_path).load().revision == 1


def test_recover_missing_active_uses_authenticated_key_for_collision_check(tmp_path) -> None:
    ownership_root = tmp_path / "host-global"
    ownership_root.mkdir(mode=0o700)
    root = tmp_path / "recovered-vault"
    root.mkdir()
    ledger = OwnershipLedger(ownership_root)
    ledger.load()

    recovered = ledger.recover_missing_active(
        channel_id="dev",
        vault_binding_id="binding-recovered",
        root=root,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )

    assert recovered.state == "active"
    assert ledger.require_existing().leases["binding-recovered"] == recovered


def _legacy_root_identity(root: Path, secret: bytes) -> tuple[str, list[str]]:
    identity = resolve_filesystem_root_identity(root.resolve(strict=False))
    primary = (
        f"inode:{identity.device}:{identity.inode}"
        if identity.materialized
        else f"path:{identity.canonical_path}"
    )
    legacy_ancestors: list[str] = []
    for ancestor in root.resolve(strict=False).parents:
        identity = resolve_filesystem_root_identity(ancestor)
        material = (
            f"inode:{identity.device}:{identity.inode}"
            if identity.materialized
            else f"path:{identity.canonical_path}"
        )
        legacy_ancestors.append(
            hmac.new(secret, material.encode("utf-8"), hashlib.sha256).hexdigest()
        )
    return (
        hmac.new(secret, primary.encode("utf-8"), hashlib.sha256).hexdigest(),
        legacy_ancestors,
    )


def _rewrite_ledger_as_authenticated_v1(
    ledger: OwnershipLedger,
    *roots: Path,
) -> bytes:
    key_payload = json.loads(ledger.key_path.read_text(encoding="utf-8"))
    secret = base64.b64decode(key_payload["secret"], validate=True)
    ancestors_by_root = dict(_legacy_root_identity(root, secret) for root in roots)
    payload = json.loads(ledger.path.read_text(encoding="utf-8"))
    payload["schema"] = ownership_ledger_module.LEGACY_LEDGER_SCHEMA
    identity_records = [*payload["leases"].values(), *payload["tombstones"].values()]
    if payload["transfer"] is not None:
        identity_records.append(payload["transfer"])
    identity_records.extend(payload["transfer_lineage"])
    for record in identity_records:
        record["ancestor_fingerprints"] = ancestors_by_root[record["root_fingerprint"]]

    before = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ledger.path.write_bytes(before)
    ledger.path.chmod(0o600)
    return before


def test_existing_ancestor_fingerprints_converge_before_new_representation_is_required(
    tmp_path,
) -> None:
    ownership_root = tmp_path / "host-global"
    ownership_root.mkdir(mode=0o700)
    root = tmp_path / "existing-vault"
    root.mkdir()
    ledger = OwnershipLedger(ownership_root)
    ledger.reserve(
        channel_id="dev",
        vault_binding_id="binding-existing",
        root=root,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    original = ledger.activate(
        "binding-existing",
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    legacy_bytes = _rewrite_ledger_as_authenticated_v1(ledger, root)

    migrated = ledger.require_registry_consistency(
        channel_id="dev",
        registrations={"binding-existing": root},
        tombstones={},
        transfer_lineage=(),
        global_live_owners=(LegacyOwner("dev", "binding-existing", root),),
    )

    assert migrated.schema == ownership_ledger_module.LEDGER_SCHEMA
    assert migrated.leases["binding-existing"].channel_id == original.channel_id
    assert migrated.leases["binding-existing"].root_fingerprint == original.root_fingerprint
    assert migrated.leases["binding-existing"].sealed_root == original.sealed_root
    assert (
        migrated.leases["binding-existing"].ancestor_fingerprints == original.ancestor_fingerprints
    )
    assert ledger.path.read_bytes() != legacy_bytes


def test_v1_schema_accepts_an_already_converged_ancestor_representation(tmp_path) -> None:
    ownership_root = tmp_path / "host-global"
    ownership_root.mkdir(mode=0o700)
    root = tmp_path / "existing-vault"
    root.mkdir()
    ledger = OwnershipLedger(ownership_root)
    ledger.reserve(
        channel_id="dev",
        vault_binding_id="binding-existing",
        root=root,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    ledger.activate("binding-existing", _capability=STORAGE_MUTATION_CAPABILITY)
    expected = ledger.require_existing()
    payload = json.loads(ledger.path.read_text(encoding="utf-8"))
    payload["schema"] = ownership_ledger_module.LEGACY_LEDGER_SCHEMA
    ledger.path.write_text(json.dumps(payload), encoding="utf-8")
    ledger.path.chmod(0o600)

    migrated = ledger.require_registry_consistency(
        channel_id="dev",
        registrations={"binding-existing": root},
        tombstones={},
        transfer_lineage=(),
        global_live_owners=(LegacyOwner("dev", "binding-existing", root),),
    )
    assert migrated.schema == expected.schema
    assert migrated.leases == expected.leases
    assert migrated.tombstones == expected.tombstones
    assert migrated.transfer == expected.transfer
    assert migrated.transfer_lineage == expected.transfer_lineage
    assert migrated.legacy_bootstrap_complete


def test_v1_namespace_legacy_proof_uses_only_portable_ancestors(tmp_path, monkeypatch) -> None:
    ownership_root = tmp_path / "host-global"
    ownership_root.mkdir(mode=0o700)
    root = tmp_path / "existing-vault"
    root.mkdir()
    ledger = OwnershipLedger(ownership_root)
    ledger.reserve(
        channel_id="dev",
        vault_binding_id="binding-existing",
        root=root,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    ledger.activate("binding-existing", _capability=STORAGE_MUTATION_CAPABILITY)
    legacy_bytes = _rewrite_ledger_as_authenticated_v1(ledger, root)
    payload = json.loads(legacy_bytes)
    stored_ancestors = payload["leases"]["binding-existing"]["ancestor_fingerprints"]
    stored_ancestors.append("f" * 64)
    ledger.path.write_text(json.dumps(payload), encoding="utf-8")
    ledger.path.chmod(0o600)
    monkeypatch.setattr(ownership_ledger_module, "LEGACY_PORTABLE_ROOTS", (tmp_path,))

    migrated = ledger.require_registry_consistency(
        channel_id="dev",
        registrations={"binding-existing": root},
        tombstones={},
        transfer_lineage=(),
        global_live_owners=(LegacyOwner("dev", "binding-existing", root),),
    )

    assert migrated.schema == ownership_ledger_module.LEDGER_SCHEMA
    assert migrated.leases["binding-existing"].ancestor_fingerprints == ledger.require_existing().leases[
        "binding-existing"
    ].ancestor_fingerprints


def test_populated_registry_finalization_migrates_authenticated_v1_ledger(tmp_path) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "instance-state", "prod")
    runtime = runtime_module.InstanceRegistryRuntime.for_paths(
        layout, tmp_path / "host-global"
    )
    root = tmp_path / "vault"
    root.mkdir()
    runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    proof, owner_inventory = establish_authority_window(runtime, tmp_path / "window")
    _rewrite_ledger_as_authenticated_v1(runtime.ledger, root)

    finish_authority_window(runtime, tmp_path / "window", proof, owner_inventory)

    migrated = runtime.ledger.require_existing()
    assert migrated.schema == ownership_ledger_module.LEDGER_SCHEMA
    assert migrated.legacy_bootstrap_complete


def test_authenticated_v1_rotation_journal_is_converged_and_consumed(tmp_path) -> None:
    ownership_root = tmp_path / "host-global"
    ownership_root.mkdir(mode=0o700)
    root = tmp_path / "existing-vault"
    root.mkdir()
    ledger = OwnershipLedger(ownership_root)
    ledger.reserve(
        channel_id="dev",
        vault_binding_id="binding-existing",
        root=root,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    ledger.activate("binding-existing", _capability=STORAGE_MUTATION_CAPABILITY)
    _rewrite_ledger_as_authenticated_v1(ledger, root)
    ledger.rotation_path.write_text(
        json.dumps(
            {
                "schema": ownership_ledger_module.ROTATION_SCHEMA,
                "key": json.loads(ledger.key_path.read_text(encoding="utf-8")),
                "ledger": json.loads(ledger.path.read_text(encoding="utf-8")),
            }
        ),
        encoding="utf-8",
    )
    ledger.rotation_path.chmod(0o600)

    migrated = ledger.require_registry_consistency(
        channel_id="dev",
        registrations={"binding-existing": root},
        tombstones={},
        transfer_lineage=(),
        global_live_owners=(LegacyOwner("dev", "binding-existing", root),),
    )

    assert migrated.schema == ownership_ledger_module.LEDGER_SCHEMA
    assert migrated.legacy_bootstrap_complete
    assert not ledger.rotation_path.exists()
    assert ledger.require_existing() == migrated


def test_v1_tampered_owner_fields_are_not_migrated(tmp_path) -> None:
    ownership_root = tmp_path / "host-global"
    ownership_root.mkdir(mode=0o700)
    root = tmp_path / "existing-vault"
    root.mkdir()
    ledger = OwnershipLedger(ownership_root)
    ledger.reserve(
        channel_id="dev",
        vault_binding_id="binding-existing",
        root=root,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    ledger.activate("binding-existing", _capability=STORAGE_MUTATION_CAPABILITY)
    payload = json.loads(_rewrite_ledger_as_authenticated_v1(ledger, root))
    payload["leases"]["binding-existing"]["channel_id"] = "prod"
    before = json.dumps(payload).encode()
    ledger.path.write_bytes(before)
    ledger.path.chmod(0o600)

    with pytest.raises(LedgerError, match="owner fields are not registry-authenticated"):
        ledger.require_registry_consistency(
            channel_id="dev",
            registrations={"binding-existing": root},
            tombstones={},
            transfer_lineage=(),
            global_live_owners=(LegacyOwner("dev", "binding-existing", root),),
        )

    assert ledger.path.read_bytes() == before


def test_v1_coherent_owner_rename_is_not_migrated(tmp_path) -> None:
    ownership_root = tmp_path / "host-global"
    ownership_root.mkdir(mode=0o700)
    root = tmp_path / "existing-vault"
    root.mkdir()
    renamed_root = tmp_path / "renamed-vault"
    renamed_root.mkdir()
    ledger = OwnershipLedger(ownership_root)
    ledger.reserve(
        channel_id="dev",
        vault_binding_id="binding-existing",
        root=root,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    ledger.activate("binding-existing", _capability=STORAGE_MUTATION_CAPABILITY)
    payload = json.loads(_rewrite_ledger_as_authenticated_v1(ledger, root))
    lease = payload["leases"].pop("binding-existing")
    lease["channel_id"] = "prod"
    lease["vault_binding_id"] = "binding-renamed"
    payload["leases"]["binding-renamed"] = lease
    before = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ledger.path.write_bytes(before)
    ledger.path.chmod(0o600)

    with pytest.raises(LedgerError, match="owner fields are not registry-authenticated"):
        ledger.require_registry_consistency(
            channel_id="prod",
            registrations={"binding-renamed": renamed_root},
            tombstones={},
            transfer_lineage=(),
            global_live_owners=(LegacyOwner("prod", "binding-renamed", renamed_root),),
        )

    assert ledger.path.read_bytes() == before


def test_valid_v1_rotation_journal_recovers_all_authority_surfaces(tmp_path) -> None:
    ownership_root = tmp_path / "host-global"
    ownership_root.mkdir(mode=0o700)
    roots = tuple(tmp_path / name for name in ("live", "transferred", "pending-transfer"))
    for root in roots:
        root.mkdir()
    ledger = OwnershipLedger(ownership_root)
    for channel_id, binding_id, root in (
        ("dev", "binding-live", roots[0]),
        ("test", "binding-source", roots[1]),
        ("dev", "binding-pending-source", roots[2]),
    ):
        ledger.reserve(
            channel_id=channel_id,
            vault_binding_id=binding_id,
            root=root,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
        ledger.activate(binding_id, _capability=STORAGE_MUTATION_CAPABILITY)
    ledger.begin_transfer(
        source_binding_id="binding-source",
        destination_channel_id="prod",
        destination_binding_id="binding-destination",
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    ledger.activate_transfer(_capability=STORAGE_MUTATION_CAPABILITY)
    ledger.begin_transfer(
        source_binding_id="binding-pending-source",
        destination_channel_id="test",
        destination_binding_id="binding-pending-destination",
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    original = ledger.require_existing()
    _rewrite_ledger_as_authenticated_v1(ledger, *roots)
    journal_payload = {
        "schema": ownership_ledger_module.ROTATION_SCHEMA,
        "key": json.loads(ledger.key_path.read_text(encoding="utf-8")),
        "ledger": json.loads(ledger.path.read_text(encoding="utf-8")),
    }
    ledger.rotation_path.write_text(json.dumps(journal_payload), encoding="utf-8")
    ledger.rotation_path.chmod(0o600)
    before_key = ledger.key_path.read_bytes()
    before_ledger = ledger.path.read_bytes()
    before_journal = ledger.rotation_path.read_bytes()

    with pytest.raises(LedgerError, match="requires fenced registry authority"):
        ledger.require_existing()
    assert ledger.key_path.read_bytes() == before_key
    assert ledger.path.read_bytes() == before_ledger
    assert ledger.rotation_path.read_bytes() == before_journal
    assert original.schema == ownership_ledger_module.LEDGER_SCHEMA


def test_malformed_or_unknown_ledger_state_refuses_without_reset(tmp_path) -> None:
    def write_private_json(path: Path, payload: object) -> bytes:
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.chmod(0o600)
        return path.read_bytes()

    def prepared_ledger(case: str) -> tuple[OwnershipLedger, bytes, bytes]:
        ownership_root = tmp_path / case / "host-global"
        ownership_root.mkdir(parents=True, mode=0o700)
        root = tmp_path / case / "vault"
        root.mkdir()
        ledger = OwnershipLedger(ownership_root)
        ledger.reserve(
            channel_id="dev",
            vault_binding_id="binding-existing",
            root=root,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
        ledger.activate(
            "binding-existing",
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
        _rewrite_ledger_as_authenticated_v1(ledger, root)
        return ledger, ledger.path.read_bytes(), ledger.key_path.read_bytes()

    malformed, _, malformed_key = prepared_ledger("malformed")
    malformed.path.write_bytes(b"{not-json\n")
    malformed_before = malformed.path.read_bytes()
    with pytest.raises(LedgerError, match="ownership ledger is invalid"):
        malformed.require_existing()
    assert malformed.path.read_bytes() == malformed_before
    assert malformed.key_path.read_bytes() == malformed_key

    unknown, unknown_before, unknown_key = prepared_ledger("unknown")
    unknown_payload = json.loads(unknown_before)
    unknown_payload["schema"] = "agentic-pkm.host-ownership-ledger.v999"
    unknown.path.write_text(json.dumps(unknown_payload), encoding="utf-8")
    unknown.path.chmod(0o600)
    unknown_before = unknown.path.read_bytes()
    with pytest.raises(LedgerError, match="ownership ledger is invalid"):
        unknown.require_existing()
    assert unknown.path.read_bytes() == unknown_before
    assert unknown.key_path.read_bytes() == unknown_key

    for case, field, value in (
        ("boolean-generation", "generation", True),
        ("integer-key-id", "key_id", 7),
        ("string-bootstrap-marker", "legacy_bootstrap_complete", "false"),
    ):
        malformed_scalar, malformed_scalar_before, malformed_scalar_key = prepared_ledger(case)
        malformed_scalar_payload = json.loads(malformed_scalar_before)
        malformed_scalar_payload[field] = value
        malformed_scalar_before = write_private_json(
            malformed_scalar.path,
            malformed_scalar_payload,
        )
        with pytest.raises(LedgerError, match="ownership ledger is invalid"):
            malformed_scalar.require_existing()
        assert malformed_scalar.path.read_bytes() == malformed_scalar_before
        assert malformed_scalar.key_path.read_bytes() == malformed_scalar_key

    for case, field, value in (
        ("malformed-key-id", "key_id", 7),
        ("malformed-key-generation", "generation", True),
    ):
        malformed_key, malformed_key_ledger, malformed_key_before = prepared_ledger(case)
        malformed_key_payload = json.loads(malformed_key_before)
        malformed_key_payload[field] = value
        malformed_key_before = write_private_json(
            malformed_key.key_path,
            malformed_key_payload,
        )
        with pytest.raises(LedgerKeyError, match="protected ownership key is invalid"):
            malformed_key.require_existing()
        assert malformed_key.path.read_bytes() == malformed_key_ledger
        assert malformed_key.key_path.read_bytes() == malformed_key_before

    malformed_journal, malformed_journal_ledger, malformed_journal_key = prepared_ledger(
        "malformed-journal"
    )
    journal_payload = {
        "schema": ownership_ledger_module.ROTATION_SCHEMA,
        "key": json.loads(malformed_journal_key),
        "ledger": json.loads(malformed_journal_ledger),
    }
    journal_payload["key"]["generation"] = True
    journal_payload["ledger"]["generation"] = True
    journal_before = write_private_json(
        malformed_journal.rotation_path,
        journal_payload,
    )
    with pytest.raises(LedgerKeyError, match="ownership key rotation journal is invalid"):
        malformed_journal.require_existing()
    assert malformed_journal.path.read_bytes() == malformed_journal_ledger
    assert malformed_journal.key_path.read_bytes() == malformed_journal_key
    assert malformed_journal.rotation_path.read_bytes() == journal_before

    unknown_state, unknown_state_before, unknown_state_key = prepared_ledger("unknown-state")
    unknown_state_payload = json.loads(unknown_state_before)
    unknown_state_payload["leases"]["binding-existing"]["state"] = "foreign"
    unknown_state.path.write_text(json.dumps(unknown_state_payload), encoding="utf-8")
    unknown_state.path.chmod(0o600)
    unknown_state_before = unknown_state.path.read_bytes()
    with pytest.raises(
        LedgerError,
        match="ownership ledger is invalid",
    ):
        unknown_state.require_existing()
    assert unknown_state.path.read_bytes() == unknown_state_before
    assert unknown_state.key_path.read_bytes() == unknown_state_key

    malformed_authority, malformed_authority_before, malformed_authority_key = prepared_ledger(
        "malformed-authority"
    )
    malformed_authority_payload = json.loads(malformed_authority_before)
    malformed_authority_payload["leases"]["binding-existing"]["channel_id"] = 7
    malformed_authority.path.write_text(json.dumps(malformed_authority_payload), encoding="utf-8")
    malformed_authority.path.chmod(0o600)
    malformed_authority_before = malformed_authority.path.read_bytes()
    with pytest.raises(
        LedgerError,
        match="ownership ledger is invalid",
    ):
        malformed_authority.require_existing()
    assert malformed_authority.path.read_bytes() == malformed_authority_before
    assert malformed_authority.key_path.read_bytes() == malformed_authority_key

    tampered_ancestor, tampered_ancestor_before, tampered_ancestor_key = prepared_ledger(
        "tampered-ancestor"
    )
    tampered_ancestor_payload = json.loads(tampered_ancestor_before)
    tampered_ancestor_payload["leases"]["binding-existing"]["ancestor_fingerprints"][0] = (
        "0" * 64
    )
    tampered_ancestor_before = write_private_json(
        tampered_ancestor.path,
        tampered_ancestor_payload,
    )
    with pytest.raises(
        LedgerError,
        match="owner fields are not registry-authenticated",
    ):
        tampered_ancestor.require_registry_consistency(
            channel_id="dev",
            registrations={
                "binding-existing": tampered_ancestor.path.parent.parent / "vault"
            },
            tombstones={},
            transfer_lineage=(),
            global_live_owners=(
                LegacyOwner(
                    "dev",
                    "binding-existing",
                    tampered_ancestor.path.parent.parent / "vault",
                ),
            ),
        )
    assert tampered_ancestor.path.read_bytes() == tampered_ancestor_before
    assert tampered_ancestor.key_path.read_bytes() == tampered_ancestor_key

    unauthenticated, unauthenticated_before, unauthenticated_key = prepared_ledger(
        "unauthenticated"
    )
    unauthenticated_payload = json.loads(unauthenticated_before)
    unauthenticated_payload["leases"]["binding-existing"]["sealed_root"] = "tampered"
    unauthenticated.path.write_text(json.dumps(unauthenticated_payload), encoding="utf-8")
    unauthenticated.path.chmod(0o600)
    unauthenticated_before = unauthenticated.path.read_bytes()

    with pytest.raises(
        LedgerError,
        match="legacy ownership ledger requires fenced registry authority",
    ):
        unauthenticated.require_existing()
    assert unauthenticated.path.read_bytes() == unauthenticated_before
    assert unauthenticated.key_path.read_bytes() == unauthenticated_key


@pytest.mark.parametrize("missing_artifact", ["ledger", "key"])
def test_floor_producer_does_not_recreate_lost_established_authority(
    tmp_path, monkeypatch, missing_artifact
) -> None:
    command, registry_path, host_global_root = _floor_command(tmp_path, monkeypatch)
    assert runtime_module.main(command) == 0
    ledger = OwnershipLedger(host_global_root)
    missing_path = ledger.path if missing_artifact == "ledger" else ledger.key_path
    surviving_path = ledger.key_path if missing_artifact == "ledger" else ledger.path
    surviving_before = surviving_path.read_bytes()
    missing_path.unlink()

    with pytest.raises(LedgerKeyError):
        runtime_module.main(command)

    assert not missing_path.exists()
    assert surviving_path.read_bytes() == surviving_before
    assert VaultRegistryStore(registry_path).load().revision == 1


def test_floor_producer_resumes_revision_zero_key_only_initialization(
    tmp_path, monkeypatch
) -> None:
    command, registry_path, host_global_root = _floor_command(tmp_path, monkeypatch)
    assert VaultRegistryStore(registry_path).load().revision == 0
    ledger = OwnershipLedger(host_global_root)
    seeded = ledger.load()
    ledger.path.unlink()

    assert runtime_module.main(command) == 0

    resumed = ledger.require_existing()
    assert (resumed.key_id, resumed.generation) == (seeded.key_id, seeded.generation)
    assert VaultRegistryStore(registry_path).load().revision == 1


def test_floor_producer_rejects_revision_zero_ledger_without_key(
    tmp_path, monkeypatch
) -> None:
    command, registry_path, host_global_root = _floor_command(tmp_path, monkeypatch)
    assert VaultRegistryStore(registry_path).load().revision == 0
    ledger = OwnershipLedger(host_global_root)
    ledger.load()
    ledger.key_path.unlink()

    with pytest.raises(LedgerKeyError, match="without its protected key"):
        runtime_module.main(command)

    assert ledger.path.is_file()
    assert not ledger.key_path.exists()
    assert VaultRegistryStore(registry_path).load().revision == 0


def test_fence_inventory_covers_every_enabled_db_outbox_process(tmp_path) -> None:
    compose_path = REPO_ROOT / "docker-compose.yaml"
    plan = discover_db_producer_fence(compose_path)
    compose = yaml.safe_load(compose_path.read_text())
    discovered = {
        name
        for name, service in compose["services"].items()
        if "db" in (service.get("depends_on") or {})
    }
    assert set(plan.db_clients) == discovered
    assert set(plan.stopped_services) | {plan.migration_runner} == discovered
    for service_name in plan.stopped_services:
        environment = compose["services"][service_name].get("environment") or {}
        if isinstance(environment, list):
            environment = {
                str(item).split("=", 1)[0]: str(item).split("=", 1)[-1]
                for item in environment
            }
        assert "INSTANCE_VAULT_REGISTRY_PATH" in environment, service_name
        assert "INSTANCE_OWNERSHIP_ROOT" in environment, service_name

    changed = yaml.safe_load(compose_path.read_text())
    changed["services"]["unfenced-writer"] = {
        "command": ["python", "-m", "app.some_writer"],
        "depends_on": {"db": {"condition": "service_healthy"}},
    }
    changed_path = tmp_path / "docker-compose.yaml"
    changed_path.write_text(yaml.safe_dump(changed), encoding="utf-8")
    with pytest.raises(Mvr05CutoverError, match="lacks one valid"):
        discover_db_producer_fence(changed_path)

    changed["services"]["unfenced-writer"]["labels"] = {
        "com.agentic-pkm.mvr05.db-role": "client"
    }
    changed_path.write_text(yaml.safe_dump(changed), encoding="utf-8")
    changed_plan = discover_db_producer_fence(changed_path)
    assert "unfenced-writer" in changed_plan.stopped_services

    del changed["services"]["migrate"]
    changed_path.write_text(yaml.safe_dump(changed), encoding="utf-8")
    with pytest.raises(Mvr05CutoverError, match="exactly one migration runner"):
        discover_db_producer_fence(changed_path)


def test_compatibility_translator_keeps_existing_producers_live_without_legacy_rows(
    tmp_path, monkeypatch
) -> None:
    registry, root = _active_runtime(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    class Cursor:
        def fetchone(self):
            return ("stored-id",)

    class Conn:
        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params
            return Cursor()

        def commit(self):
            return None

    event = new_event(event_type="test.compatibility", payload={"value": 1})
    outbox.write_outbox_event(event, conn=Conn(), idempotency_key="legacy-key")
    params = captured["params"]
    assert isinstance(params, tuple)
    assert params[6] == "binding-a"
    assert "legacy-compatibility-binding" not in params
    stored = params[2]
    assert '"vault_binding_id":"binding-a"' in stored
    assert f'"vault_root":"{root}"' in stored
    assert '"binding_authority":"allow"' in stored
    assert '"binding_authorization_epoch":' in stored
    assert f'"binding_revision":{registry.load().revision}' in stored
