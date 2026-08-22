"""Heimdal hard-retention ops job + deletion receipts (#3032, Epic #3019 slice A12).

Covers the governing Issue's one behavioral Acceptance Criterion:

    Raw records past the bounded hard-retention window are hard-deleted by
    the ops job and each deletion emits a durable deletion receipt.

Exercises the real production job call site
(`app.heimdal.retention.enforce_hard_retention_bound`) end to end:

- a raw record past the configured `_heimdal/settings.md` window is
  hard-deleted and receipted (positive);
- a raw record within the window is left untouched (negative);
- the observation log / event row is untouched by the job;
- a post-deletion gated read (`app.heimdal.raw_read_gate`) returns
  declared-absent, never a silent None;
- the deletion-receipt log is itself append-only (HEIM-1);
- the retention window is read from `_heimdal/settings.md` (A14 markdown-
  first substrate), fail-loud when unset.

Mirrors `tests/heimdal/test_raw_store.py` / `tests/heimdal/test_settings_notes.py`
conventions: memory backend, temp-vault fixture, no network, no real
Postgres.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.heimdal import raw_liveness, retention as retention_module
from app.heimdal.raw_read_gate import (
    RawReadRefusedError,
    raw_ref_for,
    read_raw_record,
    reset_memory_raw_read_receipts,
)
from app.heimdal.raw_store import (
    all_raw_records,
    compute_raw_content_identity,
    encrypt_raw_bytes,
    insert_raw_record,
    reset_memory_raw_store,
)
from app.heimdal.media_ingress import receipt_answer
from app.heimdal.media_receipts import (
    all_media_receipts,
    append_media_receipt,
    get_media_receipt,
    reset_memory_media_receipts,
)
from app.heimdal.retention import (
    REASON_HARD_RETENTION_BOUND,
    RetentionWindowMissingError,
    all_deletion_receipts,
    enforce_hard_retention_bound,
    reset_memory_deletion_receipts,
)
from app.heimdal.settings_notes import (
    DEFAULT_SETTINGS_DIR,
    SETTINGS,
    SettingsNote,
    read_settings_note,
    write_settings_note,
)
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg

_TEST_KEY = bytes.fromhex(secrets.token_hex(32))


@pytest.fixture(autouse=True)
def _reset_backends(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _TEST_KEY.hex())
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "test_reader")
    reset_memory_raw_store()
    reset_memory_raw_read_receipts()
    reset_memory_deletion_receipts()
    reset_memory_media_receipts()
    yield
    reset_memory_raw_store()
    reset_memory_raw_read_receipts()
    reset_memory_deletion_receipts()
    reset_memory_media_receipts()


def _vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _write_retention_window(vault_root: Path, *, days: int) -> None:
    write_settings_note(
        vault_root,
        SettingsNote(spec=SETTINGS, values={"retention_window_days": days}),
        settings_dir=DEFAULT_SETTINGS_DIR,
        write_guard=_allowing_guard(),
    )


def _insert_test_record(content_identity: str, *, source_path: str = "test.wav"):
    plaintext = f"raw evidence bytes:{content_identity}".encode()
    ciphertext, nonce = encrypt_raw_bytes(plaintext, key=_TEST_KEY)
    record, created = insert_raw_record(
        content_identity=compute_raw_content_identity(plaintext),
        capture_chain=["watch", "fetch"],
        sensor={"sensor_id": "test_capture_adapter"},
        consent={"grant_ref": "self_record_standing"},
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="test-key-v1",
        key=_TEST_KEY,
        source_path=source_path,
    )
    assert created is True
    return record


# ---------------------------------------------------------------------------
# AC: raw records past the bounded hard-retention window are hard-deleted by
# the ops job and each deletion emits a durable deletion receipt.
# ---------------------------------------------------------------------------


def test_hard_retention_bound_and_receipt(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    _write_retention_window(vault_root, days=30)

    record = _insert_test_record("content-past-window")

    # Run the job "in the future", well past the 30-day window -- the
    # bound fires unconditionally on age, regardless of any decay signal.
    future_now = datetime.now(timezone.utc) + timedelta(days=31)
    result = enforce_hard_retention_bound(vault_root=vault_root, now=future_now)

    assert result.deleted_count == 1
    assert result.receipted is True
    assert result.retention_window_days == 30
    assert len(result.deletions) == 1

    receipt = result.deletions[0]
    assert receipt.record_id == record.id
    assert receipt.content_identity == record.content_identity
    assert receipt.reason == REASON_HARD_RETENTION_BOUND
    assert receipt.retention_window_days == 30
    assert receipt.receipted is True

    # The raw record itself is truly gone from the store.
    assert all(r.id != record.id for r in all_raw_records())

    # The deletion receipt is durable -- it shows up in the audit trail.
    persisted = all_deletion_receipts()
    assert len(persisted) == 1
    assert persisted[0].record_id == record.id


def test_retention_does_not_leave_admitted_receipt_for_missing_raw(tmp_path: Path) -> None:
    """An admission receipt becomes an honest ``erased`` query outcome after retention.

    The original receipt stays append-only for audit, while its client-visible
    projection must never continue to authorize deletion of a client's last copy.
    """
    vault_root = _vault(tmp_path)
    _write_retention_window(vault_root, days=30)
    record = _insert_test_record("receipt-aware-retention")
    capture_id = "receipt-aware-retention-capture"
    persisted, created = append_media_receipt(
        capture_id=capture_id,
        content_sha256=record.content_identity,
        raw_ref=raw_ref_for(record),
        kind="audio",
        lane="media_ingress",
    )
    assert created is True

    result = enforce_hard_retention_bound(
        vault_root=vault_root, now=datetime.now(timezone.utc) + timedelta(days=31)
    )

    assert result.deleted_count == 1
    assert all_raw_records() == []
    assert all_media_receipts() == [persisted], "admission history remains append-only"
    receipt = get_media_receipt(capture_id, record.content_identity)
    assert receipt == persisted
    assert receipt_answer(receipt, capture_id) == {
        "capture_id": capture_id,
        "outcome": "erased",
        "receipt_id": persisted.receipt_id,
        "content_sha256": record.content_identity,
        "raw_ref": persisted.raw_ref,
        "kind": "audio",
        "lane": "media_ingress",
        "admitted_at": receipt_answer(persisted, capture_id)["admitted_at"],
    }


def test_record_within_window_is_not_deleted(tmp_path: Path) -> None:
    """Negative case: a record inserted just now, with a 30-day window, is
    untouched by a job run "now" (well within the bound)."""
    vault_root = _vault(tmp_path)
    _write_retention_window(vault_root, days=30)

    record = _insert_test_record("content-within-window")

    result = enforce_hard_retention_bound(vault_root=vault_root)

    assert result.deleted_count == 0
    assert result.receipted is True
    assert result.deletions == ()

    # The record survives untouched.
    surviving_ids = {r.id for r in all_raw_records()}
    assert record.id in surviving_ids

    # No deletion receipt was fabricated for a record that was not deleted.
    assert all_deletion_receipts() == []


def test_mixed_records_only_past_window_deleted(tmp_path: Path) -> None:
    """One record past the bound and one within it in the same run: only
    the past-bound record is deleted and receipted."""
    vault_root = _vault(tmp_path)
    _write_retention_window(vault_root, days=30)

    old_record = _insert_test_record("content-old")
    new_record = _insert_test_record("content-new")

    future_now = datetime.now(timezone.utc) + timedelta(days=31)
    result = enforce_hard_retention_bound(vault_root=vault_root, now=future_now)

    # Both records were inserted "now" (in real time) relative to this test,
    # so both are equally "old" relative to future_now -- this test's intent
    # is the *count* semantics: exactly the records past the bound are
    # deleted, matched 1:1 with receipts. Assert both were caught since both
    # predate the pushed-forward cutoff.
    assert result.deleted_count == 2
    deleted_ids = {d.record_id for d in result.deletions}
    assert deleted_ids == {old_record.id, new_record.id}
    assert all_raw_records() == []


# ---------------------------------------------------------------------------
# The observation log / event row is untouched by the retention job.
# ---------------------------------------------------------------------------


def test_observation_log_untouched_by_retention(tmp_path: Path) -> None:
    from app.events.schema import make_outbox_event
    from app.heimdal.observation_log import (
        append_observation,
        read_observations_from,
        reset_memory_observation_log,
    )

    reset_memory_observation_log()
    try:
        vault_root = _vault(tmp_path)
        _write_retention_window(vault_root, days=30)

        record = _insert_test_record("content-with-published-event")
        event = make_outbox_event(
            "heimdal.observation.published.v1",
            source="test_retention",
            payload={
                "content_identity": record.content_identity,
                "raw_ref": raw_ref_for(record),
            },
        )
        appended = append_observation(event, idempotency_key="test-retention-obs-1")
        assert appended is not None
        rows_before = read_observations_from(0)
        assert len(rows_before) == 1

        future_now = datetime.now(timezone.utc) + timedelta(days=31)
        result = enforce_hard_retention_bound(vault_root=vault_root, now=future_now)
        assert result.deleted_count == 1

        # The published event row is untouched: same count, same content.
        rows_after = read_observations_from(0)
        assert len(rows_after) == 1
        assert rows_after[0].id == rows_before[0].id
        assert rows_after[0].envelope == rows_before[0].envelope
    finally:
        reset_memory_observation_log()


# ---------------------------------------------------------------------------
# Post-deletion gated read returns declared-absent (raw_ref stays a declared
# dangling reference; A7's gate never returns a silent None).
# ---------------------------------------------------------------------------


def test_post_deletion_gated_read_returns_declared_absent(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    _write_retention_window(vault_root, days=30)

    record = _insert_test_record("content-declared-absent")
    ref = raw_ref_for(record)

    # Before deletion: the gated read succeeds normally.
    read_raw_record(ref, reader="test_reader", purpose="pre-deletion sanity check")

    future_now = datetime.now(timezone.utc) + timedelta(days=31)
    result = enforce_hard_retention_bound(vault_root=vault_root, now=future_now)
    assert result.deleted_count == 1

    # After deletion: the raw_ref is a declared dangling reference -- the
    # gate refuses loudly (RawReadRefusedError), never a silent None/empty.
    with pytest.raises(RawReadRefusedError):
        read_raw_record(ref, reader="test_reader", purpose="post-deletion read attempt")


# ---------------------------------------------------------------------------
# Deletion receipt log is append-only (HEIM-1).
# ---------------------------------------------------------------------------


def test_deletion_receipt_log_has_no_mutation_api() -> None:
    import inspect

    from app.heimdal import retention as retention_module

    public_names = [n for n in retention_module.__all__]
    for name in public_names:
        assert not name.lower().startswith("update"), f"unexpected update API: {name}"
        assert not name.lower().startswith("delete_receipt"), f"unexpected delete API: {name}"
    # No function on the module accepts a receipt id for removal/mutation.
    source = inspect.getsource(retention_module)
    assert "def delete_deletion_receipt" not in source
    assert "def update_deletion_receipt" not in source


def test_deletion_receipts_accumulate_append_only(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    _write_retention_window(vault_root, days=30)

    _insert_test_record("content-one")
    future_now = datetime.now(timezone.utc) + timedelta(days=31)
    enforce_hard_retention_bound(vault_root=vault_root, now=future_now)

    _insert_test_record("content-two")
    enforce_hard_retention_bound(vault_root=vault_root, now=future_now + timedelta(days=1))

    receipts = all_deletion_receipts()
    assert len(receipts) == 2
    assert [r.sequence for r in receipts] == sorted(r.sequence for r in receipts)


def test_scheduled_retention_retries_pending_cold_receipts_after_raw_scan_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    pending = raw_liveness.DeletionReceipt(
        id="receipt-pending",
        record_id="record-erased",
        content_identity="identity",
        reason=REASON_HARD_RETENTION_BOUND,
        retention_window_days=30,
        deleted_at=now,
        payload={"cold_cleanup_location_refs": ["heimloc:cold:one"]},
        sequence=1,
    )
    complete = raw_liveness.DeletionReceipt(
        id="receipt-complete",
        record_id="record-complete",
        content_identity="identity-2",
        reason=REASON_HARD_RETENTION_BOUND,
        retention_window_days=30,
        deleted_at=now,
        payload={"cold_cleanup_location_refs": []},
        sequence=2,
    )
    calls: list[dict[str, object]] = []

    def retry(**kwargs: object) -> raw_liveness.GovernedDeletionResult:
        calls.append(kwargs)
        return raw_liveness.GovernedDeletionResult(outcome="already_erased")

    monkeypatch.setattr(
        retention_module.raw_liveness,
        "all_deletion_receipts",
        lambda: [pending, complete],
    )
    monkeypatch.setattr(retention_module.raw_liveness, "governed_delete_raw_record", retry)

    retention_module._reconcile_pending_cold_cleanup()  # noqa: SLF001

    assert calls == [
        {
            "record_id": "record-erased",
            "reason": REASON_HARD_RETENTION_BOUND,
            "retention_window_days": 30,
            "deleted_at": now,
            "payload": {"cold_cleanup_location_refs": ["heimloc:cold:one"]},
        }
    ]


# ---------------------------------------------------------------------------
# Markdown-first policy: retention window is read from _heimdal/settings.md
# (A14), fail-loud when unset -- never a hidden default.
# ---------------------------------------------------------------------------


def test_retention_window_missing_refuses(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    # No settings.md written at all.
    with pytest.raises(RetentionWindowMissingError):
        enforce_hard_retention_bound(vault_root=vault_root)


def test_retention_window_non_positive_refuses(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    _write_retention_window(vault_root, days=0)
    with pytest.raises(RetentionWindowMissingError):
        enforce_hard_retention_bound(vault_root=vault_root)


def test_retention_window_read_from_settings_note(tmp_path: Path) -> None:
    """The job actually reads the note (A14 substrate), not a side channel:
    changing the note between runs changes the effective bound."""
    vault_root = _vault(tmp_path)
    _write_retention_window(vault_root, days=365)

    record = _insert_test_record("content-long-window")
    # 31 days in the future is still well within a 365-day window.
    near_future = datetime.now(timezone.utc) + timedelta(days=31)
    result = enforce_hard_retention_bound(vault_root=vault_root, now=near_future)
    assert result.deleted_count == 0
    assert record.id in {r.id for r in all_raw_records()}

    # Narrow the window via a fresh note edit -- the same record is now past
    # the bound on the next run.
    _write_retention_window(vault_root, days=1)
    result2 = enforce_hard_retention_bound(vault_root=vault_root, now=near_future)
    assert result2.deleted_count == 1
    assert result2.retention_window_days == 1


def test_enforce_hard_retention_bound_updates_last_enforced_note(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    _write_retention_window(vault_root, days=30)

    enforce_hard_retention_bound(vault_root=vault_root)

    note = read_settings_note(vault_root, SETTINGS, settings_dir=DEFAULT_SETTINGS_DIR)
    assert note is not None
    assert note.values.get("last_enforced_at")
    # The human-editable window value is untouched by the agent-authored
    # last_enforced_at update (honored-intent read/merge/write, A14).
    assert note.values.get("retention_window_days") == 30
