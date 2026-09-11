from __future__ import annotations

from pathlib import Path

import pytest

from app.events.models import new_event
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.instance.scalar_binding_runtime import resolve_scalar_binding_runtime
from app.instance.vault_registry import RegistryError, VaultRegistration, VaultRegistryStore
from app.services.outbox import derive_idempotency_key, write_outbox_event
from tests._mvr_default_vault_harness import active_runtime
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


class _RecordingConn:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, params: tuple[object, ...]) -> _RecordingConn:
        self.executed.append((sql, params))
        return self

    def fetchone(self) -> None:
        return None


def test_dormant_registry_preserves_legacy_compatibility(
    tmp_path: Path, monkeypatch
) -> None:
    """MVR-01B keeps legacy scalar authority until explicit MVR-01C cutover."""

    root = tmp_path / "vault"
    root.mkdir()
    registry = VaultRegistryStore(tmp_path / "instance" / "vault-registry.md")
    registry.register(
        VaultRegistration("binding-a", f"path:{root}", str(root)),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(registry.path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(tmp_path / "ownership"))
    monkeypatch.setenv("VAULT_ROOT", str(root))

    assert resolve_scalar_binding_runtime(vault_root=root) is None
    assert (
        resolve_scalar_binding_runtime(
            requested_binding_id=COMPATIBILITY_BINDING_ID, vault_root=root
        )
        is None
    )

    for requested_binding_id in (None, COMPATIBILITY_BINDING_ID):
        conn = _RecordingConn()
        event = new_event(
            event_type="mvr.dormant.compatibility",
            payload={"requested_binding_id": requested_binding_id},
        )
        write_outbox_event(
            event,
            conn=conn,
            idempotency_key=derive_idempotency_key(
                event.event_type, event.event_id, str(requested_binding_id)
            ),
            vault_binding_id=requested_binding_id,
        )

        assert len(conn.executed) == 1
        assert conn.executed[0][1][6] == COMPATIBILITY_BINDING_ID


def test_dormant_registry_rejects_explicit_native_binding_id(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    registry = VaultRegistryStore(tmp_path / "instance" / "vault-registry.md")
    registry.register(
        VaultRegistration("binding-a", f"path:{root}", str(root)),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(registry.path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(tmp_path / "ownership"))
    monkeypatch.setenv("VAULT_ROOT", str(root))

    conn = _RecordingConn()
    event = new_event(
        event_type="mvr.dormant.native",
        payload={"binding_id": "binding-a"},
    )
    with pytest.raises(
        RegistryError, match="native binding requires active registry authority"
    ):
        write_outbox_event(
            event,
            conn=conn,
            idempotency_key=derive_idempotency_key(
                event.event_type, event.event_id, "binding-a"
            ),
            vault_binding_id="binding-a",
        )

    assert conn.executed == []


def test_active_registry_rejects_mismatched_binding_id(
    tmp_path: Path, monkeypatch
) -> None:
    runtime, first, _ = active_runtime(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.registry.path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("VAULT_ROOT", first.path)

    with pytest.raises(
        RegistryError, match="outbox binding does not match the configured scalar root"
    ):
        resolve_scalar_binding_runtime(requested_binding_id="binding-mismatch")
