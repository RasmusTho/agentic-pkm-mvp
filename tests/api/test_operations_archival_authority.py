"""Real native raw/GAF effects; only external volume qualification is synthetic."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.routes.active_context_selection import build_selection_service, get_selection_store
from app.heimdal import local_archive, raw_liveness, raw_read_gate, raw_store
from app.ops import heimdal_cold_volume
from tests._production_operation_harness import production_operation_host
from tests.heimdal.test_local_archive_retention import (
    _ARCHIVE_REF, _KEY, _age_record, _insert, _volume_ready, _write_retention_window,
)


@pytest.fixture
def archived_host(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    host = production_operation_host(tmp_path, monkeypatch, extra_roots=("two",))
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", local_archive.OPERATION_RESTORE_SERVICE)
    raw_store.reset_memory_raw_store()
    raw_read_gate.reset_memory_raw_read_receipts()
    raw_liveness.reset_memory_deletion_receipts()
    host.raw_record = _age_record(_insert(b"synthetic operation evidence", grant_ref="synthetic-grant"),
                                  now=datetime.now(timezone.utc))
    _write_retention_window(host.root, days=30)
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    metadata = SimpleNamespace(archive_id=_ARCHIVE_REF, mountpoint=archive_root)

    def qualify(*args, **kwargs):
        proof = _volume_ready(archive_root)
        raw_store.configure_cold_archive_root(archive_root, verified_volume=proof,
                                             expected_archive_ref=_ARCHIVE_REF)
        return proof

    for module in (heimdal_cold_volume, local_archive):
        monkeypatch.setattr(module, "load_channel_archive_metadata", lambda **_: metadata)
        monkeypatch.setattr(module, "require_archive_volume_ready", qualify)
    monkeypatch.setenv("PKM_CONFIG_ROOT", str(tmp_path / "config"))
    yield host
    raw_store.reset_memory_raw_store()
    raw_read_gate.reset_memory_raw_read_receipts()
    raw_liveness.reset_memory_deletion_receipts()


def _command(host, operation="artifact.archive", request_id="archive-1"):
    proof = raw_read_gate.resolve_operation_target(raw_read_gate.raw_ref_for(host.raw_record),
        service_reader=local_archive.OPERATION_RESTORE_SERVICE)
    return host.command(operation, request_id=request_id,
        targets=[{"artifact_id": proof.raw_ref, "artifact_class": "source"}],
        arguments={}, expected_version=proof.generation)


def _clear(host):
    service = build_selection_service(get_selection_store())
    derived = service.derive("trusted_loopback")
    service.selection_store.clear(host.selection["context_selection_id"],
        principal=derived.principal, instance_identity=derived.instance_identity)


def test_qualified_archive_and_restore_use_real_native_receipts(archived_host):
    host = archived_host
    result = host.client.post("/api/operations", headers=host.headers, json=_command(host))
    assert result.status_code == 200 and result.json()["status"] == "succeeded", result.text
    assert result.json()["receipt"]["extensions"]["archival"]["stage"] == "retired"
    restored = host.client.post("/api/operations", headers=host.headers,
        json=_command(host, "artifact.restore", "restore-1"))
    assert restored.status_code == 200 and restored.json()["status"] == "succeeded", restored.text
    assert restored.json()["receipt"]["extensions"]["archival"]["stage"] == "restored"
    assert len(raw_read_gate.all_raw_read_receipts()) == 1


@pytest.mark.parametrize("stage", ["after_archive_lock", "after_operation_binding",
    "after_reservation", "after_object_write", "after_manifest_write"])
def test_archive_final_native_guard_refuses_cleared_selection(archived_host, monkeypatch, stage):
    host = archived_host
    cleared = False

    def revoke(current):
        nonlocal cleared
        if current == stage and not cleared:
            cleared = True
            _clear(host)

    monkeypatch.setattr(local_archive, "_relocation_stage_hook", revoke)
    result = host.client.post("/api/operations", headers=host.headers, json=_command(host))
    assert cleared
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "recovery_required", result.text
    active = [row for row in raw_store.all_raw_representations(host.raw_record.id) if row.active]
    assert len(active) == 1 and active[0].storage_kind == "postgres_hot"


def test_archive_native_guard_observes_expiry_after_owner_wait(archived_host, monkeypatch):
    host = archived_host
    import app.api.operation_runtime as runtime

    def expire(stage):
        if stage == "after_archive_lock":
            monkeypatch.setattr(runtime, "time", lambda: 4102444800)

    monkeypatch.setattr(local_archive, "_relocation_stage_hook", expire)
    result = host.client.post("/api/operations", headers=host.headers, json=_command(host))
    assert result.status_code == 200 and result.json()["status"] == "recovery_required", result.text
    assert all(not row.active or row.storage_kind == "postgres_hot"
               for row in raw_store.all_raw_representations(host.raw_record.id))


def test_restore_guard_runs_before_plaintext_and_native_receipt(archived_host, monkeypatch):
    host = archived_host
    assert host.client.post("/api/operations", headers=host.headers, json=_command(host)).json()["status"] == "succeeded"
    command = _command(host, "artifact.restore", "restore-refused")
    monkeypatch.setattr(raw_read_gate, "_raw_read_stage_hook", lambda _: _clear(host))
    result = host.client.post("/api/operations", headers=host.headers, json=command)
    assert result.status_code == 200 and result.json()["status"] == "recovery_required", result.text
    assert not raw_read_gate.all_raw_read_receipts()


@pytest.mark.parametrize("missing", ["HEIMDAL_RAW_READ_ALLOWLIST", "HEIMDAL_RAW_STORE_KEY"])
def test_archive_discovery_requires_fixed_owner_dependencies(archived_host, monkeypatch, missing):
    host = archived_host
    monkeypatch.delenv(missing)
    response = host.client.get("/api/operations/capabilities", headers=host.headers)
    assert response.status_code == 200, response.text
    entries = {item["resource_id"]: item for item in response.json()["items"]}
    for operation in ("artifact.archive", "artifact.restore"):
        assert entries[operation]["payload"]["support"] == "unavailable"


def test_archive_qualifies_explicit_member_of_multi_binding_selection(archived_host):
    host = archived_host
    bindings = list(host.runtime.registry.load().registrations)
    response = host.client.put("/api/companion/active-context/selection", headers=host.headers,
                               json={"vault_binding_ids": bindings})
    host.selection["context"] = response.json()["context"]
    result = host.client.post("/api/operations", headers=host.headers, json=_command(host))
    assert result.status_code == 200 and result.json()["status"] == "succeeded", result.text
    other = next(binding for binding in bindings if binding != host.binding_id)
    # No retention contract on this selected member: it stays unavailable.
    result = host.client.post("/api/operations", headers=host.headers,
        json={**_command(host, "artifact.restore", "other-restore"), "target_binding_id": other})
    assert result.status_code == 200 and result.json()["status"] == "not_supported", result.text
    assert Path(host.runtime.registry.load().registrations[other].path).is_dir()
