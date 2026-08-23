"""GAF-03 production conformance for Heimdal admitted raw media."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.archival.adapters.heimdal import HeimdalRawMediaAdapter
from app.archival.contracts import (
    ArtifactClass,
    DerivationClass,
    DurabilityClass,
    LivenessState,
    OwnerAuthority,
    PolicyProfile,
    TransitionStage,
)
from app.archival.transition import ArchivalTransitionKernel
from app.heimdal import local_archive, media_ingress, media_receipts, raw_liveness, raw_read_gate, raw_store
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

    with pytest.raises(raw_read_gate.RawReadRefusedError):
        local_archive.run_restore_drill(
            raw_read_gate.raw_ref_for(records[0]), reader="not-authorized", key=_KEY
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
