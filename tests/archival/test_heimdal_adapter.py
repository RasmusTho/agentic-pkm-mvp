"""GAF-03 production conformance for Heimdal admitted raw media."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import threading
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.archival.adapters.heimdal import HeimdalRawMediaAdapter
from app.archival.contracts import (
    AccessAuthority,
    ArchivalReceipt,
    ArtifactClass,
    ArtifactDescriptor,
    DerivationClass,
    DurabilityClass,
    LivenessState,
    OpaqueReference,
    OwnerAuthority,
    PolicyProfile,
    RepresentationRef,
    TransitionStage,
)
from app.archival.transition import (
    ArchivalTransitionKernel,
    TransitionConflict,
    TransitionResult,
)
from app.heimdal import (
    local_archive,
    media_ingress,
    media_receipts,
    raw_liveness,
    raw_read_gate,
    raw_store,
    retention,
)
from app.heimdal.consent_ledger import (
    MEDIA_CAPTURE_GRANT_REF,
    reset_memory_consent_ledger,
    revoke_consent,
)
from app.ops.heimdal_cold_volume import (
    _ARCHIVE_VOLUME_READY_ISSUER,
    _issue_archive_volume_ready,
)

pytestmark = pytest.mark.not_pg

_KEY = bytes.fromhex(secrets.token_hex(32))
_ARCHIVE_REF = "gaf03-test-archive"


@pytest.fixture(autouse=True)
def _memory_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "authorized-reader")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setattr(raw_liveness, "RESPONSE_LEASE_SECONDS", 0)
    raw_store.reset_memory_raw_store()
    raw_read_gate.reset_memory_raw_read_receipts()
    raw_liveness.reset_memory_raw_liveness()
    reset_memory_consent_ledger()
    media_receipts.reset_memory_media_receipts()


def _admit_all_modalities() -> list[raw_store.RawRecord]:
    for kind in media_ingress.MEDIA_KINDS:
        payload = f"gaf03-{kind}-raw-original".encode()
        media_ingress.admit_media_bytes(
            payload,
            capture_id=str(uuid4()),
            content_sha256=hashlib.sha256(payload).hexdigest(),
            kind=kind,
            captured_at="2026-08-01T12:00:00Z",
            device_id="gaf03-test-device",
            schema_version=1,
            trace_id=f"gaf03-{kind}",
            key=_KEY,
        )
    records = raw_store.all_raw_records()
    assert {record.payload["modality"] for record in records} == set(media_ingress.MEDIA_KINDS)
    return records


def _age_for_archive(records: list[raw_store.RawRecord], *, now: datetime) -> None:
    store = raw_store._MEMORY_STORE  # noqa: SLF001
    with store._lock:  # noqa: SLF001
        ids = {record.id for record in records}
        aged = [
            replace(row, ingested_at=now - timedelta(days=8)) if row.id in ids else row
            for row in store._rows  # noqa: SLF001
        ]
        store._rows = aged  # noqa: SLF001
        store._by_identity = {row.content_identity: row for row in aged}  # noqa: SLF001


def _archive_all(
    records: list[raw_store.RawRecord],
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, list[HeimdalRawMediaAdapter]]:
    now = datetime.now(timezone.utc)
    _age_for_archive(records, now=now)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    metadata = SimpleNamespace(mountpoint=archive_root, archive_id=_ARCHIVE_REF, channel="test")
    monkeypatch.setattr(local_archive, "load_channel_archive_metadata", lambda **_kwargs: metadata)
    monkeypatch.setattr(
        local_archive,
        "require_archive_volume_ready",
        lambda *_args, **_kwargs: _issue_archive_volume_ready(
            _ARCHIVE_REF, archive_root, _issuer=_ARCHIVE_VOLUME_READY_ISSUER
        ),
    )
    monkeypatch.setattr(local_archive, "resolve_retention_window_days", lambda _root: 30)
    receipt = local_archive.run_archive_pass(
        vault_root=tmp_path, config_root=tmp_path, channel="test", now=now
    )
    assert receipt.healthy and receipt.archived_count == len(media_ingress.MEDIA_KINDS)
    adapters = []
    for record in records:
        active = [row for row in raw_store.all_raw_representations(record.id) if row.active]
        assert len(active) == 1 and active[0].storage_kind == local_archive.ARCHIVE_STORAGE_KIND
        adapters.append(HeimdalRawMediaAdapter(record, generation=active[0].raw_generation))
    return archive_root, adapters


def test_all_admitted_raw_modalities_conform_to_archive_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = _admit_all_modalities()
    _archive_root, adapters = _archive_all(records, tmp_path=tmp_path, monkeypatch=monkeypatch)

    for record, adapter in zip(records, adapters, strict=True):
        descriptor = adapter.artifact
        assert descriptor.identity.owner is OwnerAuthority.CLASS_ADAPTER
        assert descriptor.identity.owner_native_id.token == record.id
        assert descriptor.artifact_class is ArtifactClass.SOURCE
        assert descriptor.derivation is DerivationClass.SOURCE
        assert descriptor.durability is DurabilityClass.DURABLE
        assert descriptor.policy_profile is PolicyProfile.RAW_EVIDENCE
        assert descriptor.generation.value > 0
        assert {ref.kind for ref in descriptor.provenance_refs} == {"content", "raw", "capture"}
        representations = adapter.enumerate(descriptor.identity)
        assert len(representations) == 2
        assert sum(row.stage is TransitionStage.ACTIVE for row in representations) == 1
        assert all("/" not in row.ref.opaque_id.token for row in representations)


def test_raw_media_restore_reuses_production_gated_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = _admit_all_modalities()
    _archive_root, _adapters = _archive_all(records, tmp_path=tmp_path, monkeypatch=monkeypatch)
    monkeypatch.delenv("HEIMDAL_RAW_STORE_KEY")

    for record in records:
        receipt = local_archive.run_restore_drill(
            raw_read_gate.raw_ref_for(record), reader="authorized-reader", key=_KEY
        )
        assert receipt.proven
        assert receipt.content_identity == record.content_identity
    owner_receipts = raw_read_gate.all_raw_read_receipts()
    assert len(owner_receipts) == len(media_ingress.MEDIA_KINDS)
    assert all(row.purpose == "heimdal_archive_restore_drill" for row in owner_receipts)
    assert all("path" not in row.payload for row in owner_receipts)

    first_representations = raw_store.all_raw_representations(records[0].id)
    active = next(row for row in first_representations if row.active)
    retired = next(row for row in first_representations if not row.active)
    adapter = HeimdalRawMediaAdapter(
        records[0], generation=active.raw_generation, read_key=_KEY
    )
    authority = AccessAuthority(
        OwnerAuthority.CLASS_ADAPTER,
        OpaqueReference("heimdal-reader", "authorized-reader"),
    )
    restored = ArchivalTransitionKernel(adapter).restore(
        adapter.artifact,
        authority,
        adapter.ref_for(active),
    )
    assert restored.stage is TransitionStage.RESTORED
    assert adapter.read_restore(adapter.artifact, adapter.ref_for(retired)) is None

    with pytest.raises(raw_read_gate.RawReadRefusedError):
        local_archive.run_restore_drill(
            raw_read_gate.raw_ref_for(records[0]), reader="not-authorized", key=_KEY
        )


def test_concurrent_restore_attempts_read_back_only_their_own_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = _admit_all_modalities()
    record = records[0]
    _archive_root, _adapters = _archive_all(
        records, tmp_path=tmp_path, monkeypatch=monkeypatch
    )
    active = next(
        row for row in raw_store.all_raw_representations(record.id) if row.active
    )
    adapter = HeimdalRawMediaAdapter(
        record, generation=active.raw_generation, read_key=_KEY
    )
    authority = AccessAuthority(
        OwnerAuthority.CLASS_ADAPTER,
        OpaqueReference("heimdal-reader", "authorized-reader"),
    )
    original_restore = adapter.restore
    restore_barrier = threading.Barrier(2)

    def synchronized_restore(
        artifact: ArtifactDescriptor,
        restore_authority: AccessAuthority,
        representation: RepresentationRef,
    ) -> ArchivalReceipt:
        receipt = original_restore(artifact, restore_authority, representation)
        restore_barrier.wait(timeout=5)
        return receipt

    monkeypatch.setattr(adapter, "restore", synchronized_restore)

    def restore_once() -> TransitionResult:
        return ArchivalTransitionKernel(adapter).restore(
            adapter.artifact,
            authority,
            adapter.ref_for(active),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _index: restore_once(), range(2)))

    assert all(outcome.stage is TransitionStage.RESTORED for outcome in outcomes)
    receipt_ids = {
        outcome.receipt.receipt_ref.token
        for outcome in outcomes
        if outcome.receipt is not None
    }
    assert len(receipt_ids) == 2
    owner_receipts = raw_read_gate.all_raw_read_receipts()
    assert {receipt.id for receipt in owner_receipts} == receipt_ids
    assert len(
        {
            receipt.payload["archival_restore_operation_id"]
            for receipt in owner_receipts
        }
    ) == 2
    assert len(
        {
            receipt.payload["archival_restore_correlation"]
            for receipt in owner_receipts
        }
    ) == 2


def test_archive_operation_binding_and_receipt_survive_process_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _admit_all_modalities()[0]
    now = datetime.now(timezone.utc)
    _age_for_archive([record], now=now)
    record = raw_store.resolve_active_raw_record(record.id)
    assert record is not None
    archive_root = tmp_path / "restartable-cold"
    archive_root.mkdir()

    class SimulatedProcessLoss(BaseException):
        pass

    def lose_process_after_activation(stage: str) -> None:
        if stage == "after_activation":
            raise SimulatedProcessLoss

    monkeypatch.setattr(local_archive, "_relocation_stage_hook", lose_process_after_activation)
    with pytest.raises(SimulatedProcessLoss):
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _issue_archive_volume_ready(
                _ARCHIVE_REF,
                archive_root,
                _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
            ),
        )

    manifest_path = next((archive_root / "manifests").glob("*.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    operation = manifest["gaf_operation"]
    assert operation["schema"] == "heimdal_gaf_operation.v1"
    assert operation["artifact_id"] == record.id
    assert operation["target_representation_id"] == manifest["representation_id"]
    assert operation["generation"] == manifest["raw_generation"]

    monkeypatch.setattr(local_archive, "_relocation_stage_hook", lambda _stage: None)
    recovered = local_archive.relocate_raw_record(
        record,
        archive_root=archive_root,
        archive_ref=_ARCHIVE_REF,
        now=now,
        retention_window_days=30,
        key=_KEY,
        volume_ready=lambda: _issue_archive_volume_ready(
            _ARCHIVE_REF,
            archive_root,
            _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
        ),
    )
    assert recovered.receipt.receipt_id == manifest["receipt_id"]
    assert recovered.receipt.representation_id == manifest["representation_id"]


def test_current_manifest_corruption_never_replays_terminal_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = _admit_all_modalities()
    record = records[0]
    archive_root, _adapters = _archive_all(
        records, tmp_path=tmp_path, monkeypatch=monkeypatch
    )
    active = raw_store.resolve_active_raw_record(record.id)
    assert active is not None
    manifest_path, manifest = next(
        (path, candidate)
        for path in (archive_root / "manifests").glob("*.json")
        if (candidate := json.loads(path.read_text(encoding="utf-8")))["record_id"]
        == record.id
    )
    assert manifest["gaf_operation"]["schema"] == "heimdal_gaf_operation.v1"

    corruptions = {
        "record_id": str(uuid4()),
        "receipt_id": "not-a-uuid",
        "schema": "wrong-schema",
        "encrypted_bytes": manifest["encrypted_bytes"] + 1,
        "ciphertext_sha256": "0" * 64,
    }
    for field, value in corruptions.items():
        corrupted = dict(manifest)
        corrupted[field] = value
        manifest_path.write_text(
            json.dumps(corrupted, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(TransitionConflict, match="current HAR"):
            local_archive.relocate_raw_record(
                active,
                archive_root=archive_root,
                archive_ref=_ARCHIVE_REF,
                now=datetime.now(timezone.utc),
                retention_window_days=30,
                key=_KEY,
                volume_ready=lambda: _issue_archive_volume_ready(
                    _ARCHIVE_REF,
                    archive_root,
                    _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
                ),
            )
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def test_operation_binding_crash_before_registration_reuses_exact_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _admit_all_modalities()[0]
    now = datetime.now(timezone.utc)
    _age_for_archive([record], now=now)
    record = raw_store.resolve_active_raw_record(record.id)
    assert record is not None
    archive_root = tmp_path / "binding-crash-cold"
    archive_root.mkdir()

    class BindingProcessLoss(BaseException):
        pass

    def lose_after_binding(stage: str) -> None:
        if stage == "after_operation_binding":
            raise BindingProcessLoss

    monkeypatch.setattr(local_archive, "_relocation_stage_hook", lose_after_binding)
    with pytest.raises(BindingProcessLoss):
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _issue_archive_volume_ready(
                _ARCHIVE_REF, archive_root, _issuer=_ARCHIVE_VOLUME_READY_ISSUER
            ),
        )
    first_manifest_path = next((archive_root / "manifests").glob("*.json"))
    first_manifest = json.loads(first_manifest_path.read_text(encoding="utf-8"))
    assert len(raw_store.all_raw_representations(record.id)) == 1

    monkeypatch.setattr(local_archive, "_relocation_stage_hook", lambda _stage: None)
    recovered = local_archive.relocate_raw_record(
        record,
        archive_root=archive_root,
        archive_ref=_ARCHIVE_REF,
        now=now,
        retention_window_days=30,
        key=_KEY,
        volume_ready=lambda: _issue_archive_volume_ready(
            _ARCHIVE_REF, archive_root, _issuer=_ARCHIVE_VOLUME_READY_ISSUER
        ),
    )
    assert recovered.receipt.representation_id == first_manifest["representation_id"]
    assert [path.name for path in (archive_root / "manifests").glob("*.json")] == [
        first_manifest_path.name
    ]


def test_registered_pending_target_requires_readable_object_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _admit_all_modalities()[0]
    now = datetime.now(timezone.utc)
    _age_for_archive([record], now=now)
    record = raw_store.resolve_active_raw_record(record.id)
    assert record is not None
    archive_root = tmp_path / "pending-manifest-cold"
    archive_root.mkdir()

    class PendingProcessLoss(BaseException):
        pass

    def lose_after_reservation(stage: str) -> None:
        if stage == "after_reservation":
            raise PendingProcessLoss

    monkeypatch.setattr(local_archive, "_relocation_stage_hook", lose_after_reservation)
    with pytest.raises(PendingProcessLoss):
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _issue_archive_volume_ready(
                _ARCHIVE_REF, archive_root, _issuer=_ARCHIVE_VOLUME_READY_ISSUER
            ),
        )
    manifest_path = next((archive_root / "manifests").glob("*.json"))
    manifest_bytes = manifest_path.read_bytes()
    pending = [
        row
        for row in raw_store.all_raw_representations(record.id)
        if row.storage_kind == local_archive.ARCHIVE_STORAGE_KIND and not row.active
    ]
    assert len(pending) == 1
    monkeypatch.setattr(local_archive, "_relocation_stage_hook", lambda _stage: None)

    for malformed in (b"{", b"[]", None):
        if malformed is None:
            manifest_path.unlink()
        else:
            manifest_path.write_bytes(malformed)
        with pytest.raises(
            local_archive.ArchiveDegradedError, match="archive_manifest_invalid"
        ):
            local_archive.relocate_raw_record(
                record,
                archive_root=archive_root,
                archive_ref=_ARCHIVE_REF,
                now=now,
                retention_window_days=30,
                key=_KEY,
                volume_ready=lambda: _issue_archive_volume_ready(
                    _ARCHIVE_REF,
                    archive_root,
                    _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
                ),
            )
        rows = raw_store.all_raw_representations(record.id)
        assert len([row for row in rows if row.active]) == 1
        assert next(row for row in rows if row.active).storage_kind == "postgres_hot"
        assert len(
            [
                row
                for row in rows
                if row.storage_kind == local_archive.ARCHIVE_STORAGE_KIND
                and not row.active
            ]
        ) == 1
        manifest_path.write_bytes(manifest_bytes)


def test_registered_terminal_target_requires_readable_object_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = _admit_all_modalities()
    record = records[0]
    archive_root, _adapters = _archive_all(
        records, tmp_path=tmp_path, monkeypatch=monkeypatch
    )
    manifest_path, manifest = next(
        (path, candidate)
        for path in (archive_root / "manifests").glob("*.json")
        if (candidate := json.loads(path.read_text(encoding="utf-8")))["record_id"]
        == record.id
    )
    manifest_bytes = manifest_path.read_bytes()

    for malformed in (b"{", b"[]", None):
        if malformed is None:
            manifest_path.unlink()
        else:
            manifest_path.write_bytes(malformed)
        with pytest.raises(
            local_archive.ArchiveDegradedError, match="archive_manifest_invalid"
        ):
            local_archive.relocate_raw_record(
                record,
                archive_root=archive_root,
                archive_ref=_ARCHIVE_REF,
                now=datetime.now(timezone.utc),
                retention_window_days=30,
                key=_KEY,
                volume_ready=lambda: _issue_archive_volume_ready(
                    _ARCHIVE_REF,
                    archive_root,
                    _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
                ),
            )
        rows = raw_store.all_raw_representations(record.id)
        active = [row for row in rows if row.active]
        assert len(active) == 1
        assert active[0].id == manifest["representation_id"]
        manifest_path.write_bytes(manifest_bytes)


def test_pending_manifest_rejects_registered_row_generation_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _admit_all_modalities()[0]
    now = datetime.now(timezone.utc)
    _age_for_archive([record], now=now)
    record = raw_store.resolve_active_raw_record(record.id)
    assert record is not None
    archive_root = tmp_path / "pending-generation-cold"
    archive_root.mkdir()

    class PendingProcessLoss(BaseException):
        pass

    def lose_after_reservation(stage: str) -> None:
        if stage == "after_reservation":
            raise PendingProcessLoss

    monkeypatch.setattr(local_archive, "_relocation_stage_hook", lose_after_reservation)
    with pytest.raises(PendingProcessLoss):
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _issue_archive_volume_ready(
                _ARCHIVE_REF, archive_root, _issuer=_ARCHIVE_VOLUME_READY_ISSUER
            ),
        )
    pending = next(
        row
        for row in raw_store.all_raw_representations(record.id)
        if row.storage_kind == local_archive.ARCHIVE_STORAGE_KIND and not row.active
    )
    store = raw_store._MEMORY_STORE  # noqa: SLF001
    with store._lock:  # noqa: SLF001
        store._representations[pending.id] = replace(  # noqa: SLF001
            pending, raw_generation=pending.raw_generation + 1
        )
    monkeypatch.setattr(local_archive, "_relocation_stage_hook", lambda _stage: None)

    with pytest.raises(TransitionConflict, match="current HAR registered generation differs"):
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _issue_archive_volume_ready(
                _ARCHIVE_REF, archive_root, _issuer=_ARCHIVE_VOLUME_READY_ISSUER
            ),
        )
    rows = raw_store.all_raw_representations(record.id)
    assert next(row for row in rows if row.active).storage_kind == "postgres_hot"


def test_terminal_manifest_rejects_registered_row_generation_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = _admit_all_modalities()
    record = records[0]
    archive_root, _adapters = _archive_all(
        records, tmp_path=tmp_path, monkeypatch=monkeypatch
    )
    active = next(
        row for row in raw_store.all_raw_representations(record.id) if row.active
    )
    store = raw_store._MEMORY_STORE  # noqa: SLF001
    with store._lock:  # noqa: SLF001
        store._representations[active.id] = replace(  # noqa: SLF001
            active, raw_generation=active.raw_generation + 1
        )

    with pytest.raises(TransitionConflict, match="current HAR registered generation differs"):
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=datetime.now(timezone.utc),
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _issue_archive_volume_ready(
                _ARCHIVE_REF, archive_root, _issuer=_ARCHIVE_VOLUME_READY_ISSUER
            ),
        )


def test_legacy_har_manifest_retry_upgrades_binding_without_fabricated_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _admit_all_modalities()[0]
    now = datetime.now(timezone.utc)
    _age_for_archive([record], now=now)
    record = raw_store.resolve_active_raw_record(record.id)
    assert record is not None
    archive_root = tmp_path / "legacy-retry-cold"
    archive_root.mkdir()

    class LegacyProcessLoss(BaseException):
        pass

    def lose_legacy_process(stage: str) -> None:
        if stage == "after_manifest_write":
            raise LegacyProcessLoss

    monkeypatch.setattr(local_archive, "_relocation_stage_hook", lose_legacy_process)
    with pytest.raises(LegacyProcessLoss):
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _issue_archive_volume_ready(
                _ARCHIVE_REF,
                archive_root,
                _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
            ),
        )

    manifest_path = next((archive_root / "manifests").glob("*.json"))
    legacy_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy_manifest.pop("gaf_operation")
    manifest_path.write_text(
        json.dumps(legacy_manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    representations = raw_store.all_raw_representations(record.id)
    assert any(row.active and row.storage_kind == "postgres_hot" for row in representations)
    assert any(
        not row.active and row.storage_kind == local_archive.ARCHIVE_STORAGE_KIND
        for row in representations
    )

    malformed_fields = {
        "schema": "wrong-schema",
        "receipt_id": "not-a-uuid",
        "encrypted_bytes": legacy_manifest["encrypted_bytes"] + 1,
        "ciphertext_sha256": "0" * 64,
        "verified_at": "not-a-timestamp",
    }
    for field, malformed in malformed_fields.items():
        candidate = dict(legacy_manifest)
        candidate[field] = malformed
        manifest_path.write_text(
            json.dumps(candidate, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(TransitionConflict, match="legacy HAR"):
            local_archive.relocate_raw_record(
                record,
                archive_root=archive_root,
                archive_ref=_ARCHIVE_REF,
                now=now,
                retention_window_days=30,
                key=_KEY,
                volume_ready=lambda: _issue_archive_volume_ready(
                    _ARCHIVE_REF,
                    archive_root,
                    _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
                ),
            )
    manifest_path.write_text(
        json.dumps(legacy_manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    def lose_after_legacy_binding(stage: str) -> None:
        if stage == "after_operation_binding":
            raise LegacyProcessLoss

    monkeypatch.setattr(local_archive, "_relocation_stage_hook", lose_after_legacy_binding)
    with pytest.raises(LegacyProcessLoss):
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _issue_archive_volume_ready(
                _ARCHIVE_REF,
                archive_root,
                _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
            ),
        )
    bound_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert bound_manifest["gaf_operation"]["schema"] == "heimdal_gaf_operation.v1"
    assert bound_manifest["receipt_id"] == legacy_manifest["receipt_id"]

    resumed_stages: list[str] = []
    monkeypatch.setattr(local_archive, "_relocation_stage_hook", resumed_stages.append)
    recovered = local_archive.relocate_raw_record(
        record,
        archive_root=archive_root,
        archive_ref=_ARCHIVE_REF,
        now=now,
        retention_window_days=30,
        key=_KEY,
        volume_ready=lambda: _issue_archive_volume_ready(
            _ARCHIVE_REF,
            archive_root,
            _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
        ),
    )
    upgraded = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert resumed_stages[0] == "after_archive_lock"
    assert resumed_stages[-1] == "after_activation"
    assert upgraded["gaf_operation"]["target_representation_id"] == recovered.receipt.representation_id
    assert upgraded["receipt_id"] == recovered.receipt.receipt_id
    assert upgraded["receipt_id"] == legacy_manifest["receipt_id"]
    assert upgraded["verified_at"] == legacy_manifest["verified_at"]
    assert upgraded["encrypted_bytes"] == legacy_manifest["encrypted_bytes"]
    assert upgraded["ciphertext_sha256"] == legacy_manifest["ciphertext_sha256"]

    upgraded["gaf_operation"]["idempotency_key"] = "conflicting-operation"
    manifest_path.write_text(
        json.dumps(upgraded, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(TransitionConflict, match="durable Heimdal operation binding differs"):
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _issue_archive_volume_ready(
                _ARCHIVE_REF,
                archive_root,
                _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
            ),
        )


def test_raw_media_revocation_preserves_har05_liveness_for_every_modality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = _admit_all_modalities()
    archive_root, adapters = _archive_all(records, tmp_path=tmp_path, monkeypatch=monkeypatch)

    revoke_consent(grant_ref=MEDIA_CAPTURE_GRANT_REF, revoked_by="gaf03-test")

    tombstones = raw_liveness.all_deletion_tombstones()
    deletion_receipts = raw_liveness.all_deletion_receipts()
    assert {row.record_id for row in tombstones} == {record.id for record in records}
    assert {row.record_id for row in deletion_receipts} == {record.id for record in records}
    assert raw_store.all_raw_records() == []
    assert list((archive_root / "representations").glob("*.bin")) == []
    assert list((archive_root / "manifests").glob("*.json")) == []

    for adapter in adapters:
        outcome = ArchivalTransitionKernel(adapter).cleanup(adapter.artifact)
        assert outcome.stage is TransitionStage.ERASED
        assert outcome.liveness.state is LivenessState.ERASED
        proof = adapter.read_cleanup(adapter.artifact)
        assert proof is not None and proof.complete


def test_cleanup_stays_pending_while_har05_cold_queue_is_not_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = _admit_all_modalities()
    _archive_root, adapters = _archive_all(records, tmp_path=tmp_path, monkeypatch=monkeypatch)
    original_delete = raw_store._delete_bound_cold_object  # noqa: SLF001

    def fail_cold_cleanup(*_args: object, **_kwargs: object) -> None:
        raise raw_store.RawRepresentationDeletionError("injected cold cleanup failure")

    monkeypatch.setattr(raw_store, "_delete_bound_cold_object", fail_cold_cleanup)
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        revoke_consent(grant_ref=MEDIA_CAPTURE_GRANT_REF, revoked_by="gaf03-test")

    pending_receipt = raw_liveness.all_deletion_receipts()[0]
    assert pending_receipt.payload["cold_cleanup_location_refs"]
    pending_adapter = next(
        adapter for adapter in adapters if adapter.record.id == pending_receipt.record_id
    )
    projected = pending_adapter.enumerate(pending_adapter.artifact.identity)
    assert len(projected) == 1
    assert projected[0].stage is TransitionStage.ERASE_PENDING
    assert projected[0].liveness.state is LivenessState.ERASURE_PENDING
    pending = ArchivalTransitionKernel(pending_adapter).cleanup(pending_adapter.artifact)
    assert pending.stage is TransitionStage.ERASE_PENDING
    assert pending.liveness.state is LivenessState.ERASURE_PENDING

    monkeypatch.setattr(raw_store, "_delete_bound_cold_object", original_delete)
    retention.enforce_consent_revocation(grant_ref=MEDIA_CAPTURE_GRANT_REF)
    terminal = ArchivalTransitionKernel(pending_adapter).cleanup(pending_adapter.artifact)
    assert terminal.stage is TransitionStage.ERASED
    assert terminal.liveness.state is LivenessState.ERASED


def test_cleanup_requires_explicit_empty_owner_queue_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = _admit_all_modalities()
    _archive_root, adapters = _archive_all(
        records, tmp_path=tmp_path, monkeypatch=monkeypatch
    )
    revoke_consent(grant_ref=MEDIA_CAPTURE_GRANT_REF, revoked_by="gaf03-test")
    adapter = adapters[0]
    receipt = raw_liveness.all_deletion_receipts()[0]
    assert receipt.payload["cold_cleanup_location_refs"] == []

    missing_queue_payload = dict(receipt.payload)
    missing_queue_payload.pop("cold_cleanup_location_refs")
    candidates = (
        replace(receipt, payload=missing_queue_payload),
        replace(receipt, record_id=str(uuid4())),
        replace(
            receipt,
            payload={**receipt.payload, "cold_cleanup_location_refs": None},
        ),
    )
    for candidate in candidates:
        monkeypatch.setattr(
            raw_liveness,
            "all_deletion_receipts",
            lambda candidate=candidate: [candidate],
        )
        assert adapter.read_cleanup(adapter.artifact) is None
        projected = adapter.enumerate(adapter.artifact.identity)
        assert len(projected) == 1
        assert projected[0].stage is TransitionStage.ERASE_PENDING
        assert projected[0].liveness.state is LivenessState.ERASURE_PENDING
