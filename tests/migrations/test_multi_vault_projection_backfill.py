from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.events.models import new_event
from app.instance._storage_boundary import CapabilityNotReadyError
from app.instance.mvr05_cutover import (
    discover_db_producer_fence,
    record_mvr05_runtime_floor,
)
from app.instance.local_operator_principal import (
    LocalOperatorPrincipalStore,
    PROVENANCE_FRESH_BOOTSTRAP,
    SUBJECT_LOOPBACK,
)
from app.instance.ownership_ledger import OwnershipLedger
from app.instance.runtime import _require_runtime_floor
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


def test_projection_upgrade_blocks_scalar_rollback_before_first_write(tmp_path) -> None:
    store = VaultRegistryStore(tmp_path / "instance" / "vault-registry.md")
    floor = record_mvr05_runtime_floor(
        store,
        fence=discover_db_producer_fence(REPO_ROOT / "docker-compose.yaml"),
        channel_id="dev",
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    assert floor.extensions["runtimeFloors"]["minimumRuntimeSchema"] == "mvr-05"
    with pytest.raises(CapabilityNotReadyError, match="blocks scalar"):
        _require_runtime_floor(floor, scalar_runtime=True)


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
    outbox.write_outbox_event(
        event,
        conn=Conn(),
        idempotency_key="legacy-key",
    )
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
