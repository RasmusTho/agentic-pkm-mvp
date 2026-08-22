from __future__ import annotations

import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from app.events.models import new_event
from app.instance import mvr05_cutover as mvr05_cutover_module
from app.instance import runtime as runtime_module
from app.instance.local_operator_principal import (
    LocalOperatorPrincipalStore,
    PROVENANCE_FRESH_BOOTSTRAP,
    SUBJECT_LOOPBACK,
)
from app.instance.mvr05_cutover import (
    Mvr05CutoverError,
    discover_db_producer_fence,
)
from app.instance.ownership_ledger import LedgerError, LedgerKeyError, OwnershipLedger
from app.instance.vault_registry import VaultRegistration, VaultRegistryStore
from app.services import outbox
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


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


def test_v1_ledger_requires_explicit_scratch_rebootstrap(tmp_path) -> None:
    ownership_root = tmp_path / "host-global"
    ownership_root.mkdir(mode=0o700)
    ledger = OwnershipLedger(ownership_root)
    ledger.load()
    payload = json.loads(ledger.path.read_text(encoding="utf-8"))
    payload["schema"] = "agentic-pkm.host-ownership-ledger.v1"
    ledger.path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        LedgerError,
        match="ownership ledger format v1 requires explicit scratch/rebootstrap reset",
    ):
        ledger.require_existing()


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
