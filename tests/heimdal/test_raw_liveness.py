"""Generation-bound raw liveness, response leases, and governed deletion."""

from __future__ import annotations

import secrets
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.heimdal import raw_liveness, raw_store
from app.heimdal.raw_read_gate import raw_ref_for
from app.heimdal.retention import (
    all_deletion_receipts,
    enforce_hard_retention_bound,
    enforce_screen_frame_retention,
    reset_memory_deletion_receipts,
)
from app.heimdal.settings_notes import SETTINGS, SettingsNote, write_settings_note
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg

_KEY = bytes.fromhex(secrets.token_hex(32))


@pytest.fixture(autouse=True)
def _memory_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    raw_store.reset_memory_raw_store()
    reset_memory_deletion_receipts()
    yield
    raw_store.reset_memory_raw_store()
    reset_memory_deletion_receipts()


def _settings(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    write_settings_note(
        root,
        SettingsNote(
            spec=SETTINGS,
            values={
                "retention_window_days": 1,
                "screen_frame_retention_minutes": 1,
            },
        ),
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    return root


def _insert(content: bytes, *, screen: bool = False) -> raw_store.RawRecord:
    ciphertext, nonce = raw_store.encrypt_raw_bytes(content, key=_KEY)
    record, created = raw_store.insert_raw_record(
        content_identity=raw_store.compute_raw_content_identity(content),
        capture_chain=["test"],
        sensor={"adapter": "raw_liveness_test"},
        consent={"grant_ref": "test-grant"},
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="test-key",
        key=_KEY,
        source_path="test.raw",
        payload={"modality": "screen" if screen else "audio"},
    )
    assert created
    return record


def _run_retention(writer: str, *, root: Path, now: datetime):
    if writer == "hard":
        return enforce_hard_retention_bound(
            vault_root=root, now=now, record_last_enforced=False
        )
    return enforce_screen_frame_retention(vault_root=root, now=now)


def test_receipt_trigger_preflight_rejects_extra_delete_return_path() -> None:
    canonical = """
        BEGIN
          IF TG_OP = 'UPDATE'
             AND current_setting('app.heimdal_retention_reconcile', true) = 'true' THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'heimdal_raw_deletion_receipt is append-only: % is not permitted', TG_OP;
        END;
    """
    trigger = (
        "CREATE TRIGGER heimdal_raw_deletion_receipt_no_update BEFORE UPDATE OR DELETE "
        "ON heimdal_raw_deletion_receipt FOR EACH ROW EXECUTE FUNCTION "
        "heimdal_raw_deletion_receipt_reject_mutation()"
    )
    assert raw_liveness._receipt_trigger_is_migration_ready(canonical, trigger)  # noqa: SLF001
    assert not raw_liveness._receipt_trigger_is_migration_ready(
        """
        BEGIN
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          IF TG_OP = 'UPDATE'
             AND current_setting('app.heimdal_retention_reconcile', true) = 'true' THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'heimdal_raw_deletion_receipt is append-only: % is not permitted', TG_OP;
        END;
        """,
        trigger,
    )  # noqa: SLF001
    assert not raw_liveness._receipt_trigger_is_migration_ready(
        """
        BEGIN
          IF TG_OP = 'UPDATE'
             AND current_setting('app.heimdal_retention_reconcile', true) = 'true' THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'heimdal_raw_deletion_receipt is append-only: % is not permitted', TG_OP
            USING HINT = side_effecting_function();
        END;
        """,
        trigger,
    )  # noqa: SLF001
    assert not raw_liveness._receipt_trigger_is_migration_ready(
        """
        BEGIN
          DELETE FROM unrelated_table;
          IF TG_OP = 'UPDATE'
             AND current_setting('app.heimdal_retention_reconcile', true) = 'true' THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'heimdal_raw_deletion_receipt is append-only: % is not permitted', TG_OP;
        END;
        """,
        trigger,
    )  # noqa: SLF001
    assert not raw_liveness._receipt_trigger_is_migration_ready(
        canonical,
        trigger + " WHEN (false)",
    )  # noqa: SLF001


@pytest.mark.parametrize("writer", ["hard", "screen"])
def test_valid_response_lease_blocks_both_retention_writers_until_expiry(
    writer: str, tmp_path: Path
) -> None:
    root = _settings(tmp_path)
    record = _insert(f"lease-{writer}".encode(), screen=writer == "screen")
    retention_time = datetime.now(timezone.utc) + timedelta(days=2)
    lease = raw_liveness.issue_response_lease(
        raw_ref=raw_ref_for(record),
        content_identity=record.content_identity,
        now=retention_time,
    )

    skipped = _run_retention(writer, root=root, now=retention_time)
    assert skipped.deleted_count == 0
    assert raw_store.get_raw_record_by_content_identity(record.content_identity) is not None
    assert all_deletion_receipts() == []

    deleted = _run_retention(
        writer, root=root, now=lease.expires_at + timedelta(microseconds=1)
    )
    assert deleted.deleted_count == 1
    assert raw_store.get_raw_record_by_content_identity(record.content_identity) is None
    assert len(raw_liveness.all_deletion_tombstones()) == 1


@pytest.mark.parametrize("writer", ["hard", "screen"])
@pytest.mark.parametrize(
    "crash_stage", ["after_deletion_receipt", "after_tombstone", "after_raw_delete"]
)
def test_governed_deletion_crash_rolls_back_raw_tombstone_and_receipt(
    writer: str,
    crash_stage: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _settings(tmp_path)
    record = _insert(
        f"crash-{writer}-{crash_stage}".encode(), screen=writer == "screen"
    )
    retention_time = datetime.now(timezone.utc) + timedelta(days=2)

    def crash(stage: str) -> None:
        if stage == crash_stage:
            raise RuntimeError(f"injected crash at {stage}")

    monkeypatch.setattr(raw_liveness, "_retention_stage_hook", crash)
    with pytest.raises(RuntimeError, match="injected crash"):
        _run_retention(writer, root=root, now=retention_time)

    assert raw_store.get_raw_record_by_content_identity(record.content_identity) is not None
    assert all_deletion_receipts() == []
    assert raw_liveness.all_deletion_tombstones() == []

    monkeypatch.setattr(raw_liveness, "_retention_stage_hook", lambda _stage: None)
    assert _run_retention(writer, root=root, now=retention_time).deleted_count == 1


def test_missing_raw_without_tombstone_is_unavailable_never_erased() -> None:
    record = _insert(b"untombstoned-absence")
    assert raw_store._MEMORY_STORE.hard_delete(record.id)  # noqa: SLF001

    with pytest.raises(raw_liveness.RawLivenessUnavailableError):
        raw_liveness.issue_response_lease(
            raw_ref=raw_ref_for(record), content_identity=record.content_identity
        )
    assert raw_liveness.all_deletion_tombstones() == []


def test_missing_active_representation_is_unavailable_never_erased() -> None:
    record = _insert(b"inactive-representation")
    with raw_store._MEMORY_STORE._lock:  # noqa: SLF001
        representation = raw_store._MEMORY_STORE._representations[record.id]  # noqa: SLF001
        raw_store._MEMORY_STORE._representations[record.id] = replace(  # noqa: SLF001
            representation, active=False
        )

    with pytest.raises(raw_liveness.RawLivenessUnavailableError):
        raw_liveness.issue_response_lease(
            raw_ref=raw_ref_for(record), content_identity=record.content_identity
        )
    assert raw_liveness.all_deletion_tombstones() == []


def test_only_governed_tombstone_yields_erased() -> None:
    record = _insert(b"governed-erasure")
    deleted_at = datetime.now(timezone.utc) + timedelta(days=2)
    result = raw_liveness.governed_delete_raw_record(
        record_id=record.id,
        reason="hard_retention_bound",
        retention_window_days=1,
        deleted_at=deleted_at,
    )
    assert result.outcome == "deleted"

    with pytest.raises(raw_liveness.RawEvidenceErasedError) as exc_info:
        raw_liveness.issue_response_lease(
            raw_ref=raw_ref_for(record), content_identity=record.content_identity
        )
    assert exc_info.value.tombstone.deletion_receipt_id == result.receipt.id


def test_same_content_reinsertion_gets_new_generation_without_resurrecting_old_ref() -> None:
    content = b"same-content-new-generation"
    old = _insert(content)
    raw_liveness.governed_delete_raw_record(
        record_id=old.id,
        reason="hard_retention_bound",
        retention_window_days=1,
        deleted_at=datetime.now(timezone.utc) + timedelta(days=2),
    )
    new = _insert(content)
    assert new.id != old.id

    new_lease = raw_liveness.issue_response_lease(
        raw_ref=raw_ref_for(new), content_identity=new.content_identity
    )
    assert new_lease.generation == 2
    with pytest.raises(raw_liveness.RawEvidenceErasedError):
        raw_liveness.issue_response_lease(
            raw_ref=raw_ref_for(old), content_identity=old.content_identity
        )


def test_retention_claim_stops_lease_reopening_while_existing_lease_drains(
    tmp_path: Path,
) -> None:
    root = _settings(tmp_path)
    record = _insert(b"shared-raw-identity")
    retention_time = datetime.now(timezone.utc) + timedelta(days=2)
    first = raw_liveness.issue_response_lease(
        raw_ref=raw_ref_for(record),
        content_identity=record.content_identity,
        now=retention_time,
    )
    result = _run_retention("hard", root=root, now=retention_time)
    assert result.deleted_count == 0
    claims = raw_liveness.all_retention_claims()
    assert len(claims) == 1
    assert claims[0].drain_after == first.expires_at
    with pytest.raises(raw_liveness.RawLivenessUnavailableError, match="retiring"):
        raw_liveness.issue_response_lease(
            raw_ref=raw_ref_for(record),
            content_identity=record.content_identity,
            now=retention_time + timedelta(seconds=1),
        )
    assert (
        _run_retention(
            "hard", root=root, now=first.expires_at + timedelta(microseconds=1)
        ).deleted_count
        == 1
    )
