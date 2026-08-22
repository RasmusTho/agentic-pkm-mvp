"""Governed media ingress with durable receipts (CDLM-01, issue #4384).

Every test here drives the **production route** (`app.api.app.app` through
`TestClient`), not a helper in isolation: the acceptance criteria are about
what an external capture client observes, and the load-bearing rule --
INV-CDLM-1, "a receipt means durable acceptance" -- is only meaningful if it
holds on the path a client actually calls.

`test_ack_requires_raw_write_and_committed_event` is the enforcement AC: it
fault-injects the real outbox commit primitive
(`app.services.outbox.append_jsonl_outbox_event`, reached through the module
attribute the ingress seam calls) and asserts both the ordering and that a
failed commit leaves *no acknowledged state* -- no receipt, no 2xx, and a
receipt query that still answers `unknown`.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from app.api.app import app
from app.heimdal import media_ingress, media_receipts, raw_liveness, raw_store
from app.heimdal.capture_adapter import admit_capture_file
from app.heimdal.consent_ledger import (
    ConsentLedgerSchemaMissingError,
    ConsentRefusedError,
    MEDIA_CAPTURE_GRANT_REF,
    MEDIA_CAPTURE_SCOPE,
    SELF_RECORD_GRANT_REF,
    reset_memory_consent_ledger,
    resolve_active_grant,
    revoke_consent,
)
from app.heimdal.media_receipts import (
    all_media_receipts,
    reset_memory_media_receipts,
)
from app.heimdal.raw_read_gate import raw_ref_for
from app.heimdal.raw_store import (
    all_raw_records,
    all_raw_representations,
    encrypt_raw_bytes,
    insert_raw_record,
    reset_memory_raw_store,
)
from app.heimdal.retention import (
    RetentionErasurePendingError,
    enforce_hard_retention_bound,
    enforce_screen_frame_retention,
)
from app.heimdal.settings_notes import SETTINGS, SettingsNote, write_settings_note
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg

_KEY = bytes.fromhex(secrets.token_hex(32))
MEDIA_ADMITTED_EVENT = "heimdal.capture.media.admitted"


@pytest.fixture(autouse=True)
def _memory_runtime(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Path:
    """Volatile Heimdal backend plus a per-test JSONL outbox sink.

    `DATABASE_URL`/`DB_DSN` are removed explicitly rather than relying on the
    root conftest's `-m "not pg"` normalization, so the suggested validation
    command (which passes no marker expression) still resolves the memory
    backend and the JSONL audit log as the single outbox sink.

    A `pg`-marked test is left alone, mirroring the root conftest's
    `force_memory_store_for_non_pg`: forcing the memory backend there would
    defeat the point of exercising the Postgres one.
    """
    if request.node.get_closest_marker("pg") is None:
        monkeypatch.setenv("STORE_BACKEND", "memory")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    reset_memory_raw_store()
    reset_memory_consent_ledger()
    reset_memory_media_receipts()
    return outbox_path


@pytest.fixture
def client() -> TestClient:
    """A loopback-posture client (`TestClient`'s default peer is loopback)."""
    return TestClient(app)


def _admitted_events(outbox_path: Path) -> list[dict[str, Any]]:
    if not outbox_path.exists():
        return []
    records = [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [record for record in records if record.get("event") == MEDIA_ADMITTED_EVENT]


def _sidecar(media: bytes, **overrides: Any) -> dict[str, Any]:
    sidecar: dict[str, Any] = {
        "capture_id": str(uuid4()),
        "content_sha256": hashlib.sha256(media).hexdigest(),
        "kind": "audio",
        "captured_at": "2026-07-29T12:00:00Z",
        "device_id": "ipad-1",
        "schema_version": 1,
    }
    sidecar.update(overrides)
    return sidecar


def _post_media(client: TestClient, media: bytes, sidecar: dict[str, Any], **kwargs: Any):
    return client.post(
        "/api/heimdal/capture/media",
        files={
            "media": ("segment-000.m4a", media, "audio/m4a"),
            "sidecar": ("sidecar.json", json.dumps(sidecar), "application/json"),
        },
        **kwargs,
    )


def _get_receipts(client: TestClient, *capture_ids: str):
    return client.get(
        "/api/heimdal/capture/receipts",
        params=[("capture_id", capture_id) for capture_id in capture_ids],
    )


def _write_retention_settings(vault_root: Path) -> None:
    write_settings_note(
        vault_root,
        SettingsNote(
            spec=SETTINGS,
            values={
                "retention_window_days": 1,
                "screen_frame_retention_minutes": 1,
            },
        ),
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )


# ---------------------------------------------------------------------------
# AC1 (enforcement): the 2xx exists only after durable raw write + committed event
# ---------------------------------------------------------------------------


def test_ack_requires_raw_write_and_committed_event(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, _memory_runtime: Path
) -> None:
    media = b"durable-media-bytes"
    sidecar = _sidecar(media)

    # --- ordering on the production route ---------------------------------
    order: list[str] = []
    real_raw_write = media_ingress.raw_store.insert_raw_record
    real_commit = media_ingress.outbox_service.append_jsonl_outbox_event
    real_receipt_write = media_ingress.media_receipts.append_media_receipt

    def traced_raw_write(**kwargs: Any):
        order.append("raw-write")
        return real_raw_write(**kwargs)

    def traced_commit(*args: Any, **kwargs: Any):
        order.append("event-commit")
        return real_commit(*args, **kwargs)

    def traced_receipt_write(**kwargs: Any):
        order.append("receipt-write")
        return real_receipt_write(**kwargs)

    monkeypatch.setattr(media_ingress.raw_store, "insert_raw_record", traced_raw_write)
    monkeypatch.setattr(media_ingress.outbox_service, "append_jsonl_outbox_event", traced_commit)
    monkeypatch.setattr(media_ingress.media_receipts, "append_media_receipt", traced_receipt_write)

    ok = _post_media(client, media, sidecar, headers={"x-trace-id": "t-cdlm01"})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["outcome"] == "admitted"
    assert body["capture_id"] == sidecar["capture_id"]
    assert body["content_sha256"] == sidecar["content_sha256"]
    assert body["receipt_id"] and body["raw_ref"] and body["admitted_at"]
    assert body["trace_id"] == "t-cdlm01"
    # The acknowledged receipt is backed by a durable row — asserted directly, so
    # no code path can satisfy this test by returning a locally-built receipt.
    persisted = media_receipts.get_media_receipt(
        sidecar["capture_id"], sidecar["content_sha256"]
    )
    assert persisted is not None and persisted.receipt_id == body["receipt_id"]
    assert persisted.raw_ref == body["raw_ref"]
    # The acknowledgement is the LAST thing that happens: the raw object is
    # durable and the admission event is committed before the receipt exists.
    assert order == ["raw-write", "event-commit", "receipt-write"]

    # --- forced event-commit failure leaves nothing acknowledged ----------
    reset_memory_raw_store()
    reset_memory_media_receipts()
    order.clear()
    # The JSONL sink is append-only across the test, so the fault path is
    # judged against the event count the successful admission above left.
    events_before_fault = len(_admitted_events(_memory_runtime))
    faulted = _sidecar(b"faulted-media-bytes")
    faulted_media = b"faulted-media-bytes"

    def failing_commit(*args: Any, **kwargs: Any):
        order.append("event-commit")
        raise OSError("outbox sink unavailable")

    monkeypatch.setattr(media_ingress.outbox_service, "append_jsonl_outbox_event", failing_commit)

    failed = _post_media(client, faulted_media, faulted)
    assert failed.status_code == 500, failed.text
    detail = failed.json()["detail"]
    assert detail["error"] == "admission_event_commit_failed"
    assert detail["state"] == "not_acknowledged"

    # Nothing acknowledged: the receipt was never written, and the recovery
    # query still answers `unknown` for this capture.
    assert order == ["raw-write", "event-commit"]
    assert all_media_receipts() == []
    assert len(_admitted_events(_memory_runtime)) == events_before_fault
    unknown = _get_receipts(client, faulted["capture_id"]).json()["receipts"]
    assert unknown == [{"capture_id": faulted["capture_id"], "outcome": "unknown"}]

    # The raw object is append-only, so the un-acknowledged write survives —
    # and the client's resend completes admission idempotently over it
    # (partial-failure matrix: "hub crash between raw write and outbox commit").
    assert len(all_raw_records()) == 1
    monkeypatch.setattr(media_ingress.outbox_service, "append_jsonl_outbox_event", real_commit)
    resent = _post_media(client, faulted_media, faulted)
    assert resent.status_code == 200, resent.text
    assert resent.json().get("idempotent_replay") is not True
    assert len(all_raw_records()) == 1
    assert len(_admitted_events(_memory_runtime)) == events_before_fault + 1


@pytest.mark.parametrize(
    "fault",
    [
        OSError("receipt store rejected the insert"),
        # The store's own durability refusal: its pg backend raises this when a
        # row was neither inserted nor readable back.
        media_receipts.MediaReceiptPersistenceError("receipt not durable"),
    ],
    ids=["arbitrary-store-fault", "store-durability-refusal"],
)
def test_receipt_write_failure_acknowledges_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, fault: Exception, _memory_runtime: Path
) -> None:
    """The receipt IS the acknowledgement, so a failed receipt write acknowledges nothing.

    The other half of AC1's enforcement: `test_ack_requires_raw_write_and_committed_event`
    fault-injects the event commit, this one fault-injects the final step. Without
    it, a seam that returned a locally-built receipt instead of a persisted row
    would answer 200 `admitted` with a `receipt_id` that has no durable row — and
    CDLM-03 would delete the client's only copy against that 200. Both fault types
    are exercised because the seam handles them on separate branches.
    """
    media = f"receipt-write-will-fail-{type(fault).__name__}".encode()
    sidecar = _sidecar(media)

    real_receipt_write = media_ingress.media_receipts.append_media_receipt

    def failing_receipt_write(**_kwargs: Any):
        raise fault

    monkeypatch.setattr(
        media_ingress.media_receipts, "append_media_receipt", failing_receipt_write
    )

    refused = _post_media(client, media, sidecar)
    assert refused.status_code == 500, refused.text
    detail = refused.json()["detail"]
    assert detail["error"] == "receipt_persistence_failed"
    assert detail["state"] == "not_acknowledged"

    # Nothing acknowledged: no receipt row, and the recovery query says so.
    # Restore only the injected fault — `monkeypatch.undo()` would also revert
    # the fixture's backend env and leave no store configured at all.
    monkeypatch.setattr(
        media_ingress.media_receipts, "append_media_receipt", real_receipt_write
    )
    assert all_media_receipts() == []
    answer = _get_receipts(client, sidecar["capture_id"]).json()["receipts"][0]
    assert answer == {"capture_id": sidecar["capture_id"], "outcome": "unknown"}

    # The event did commit before the receipt failed, so the resend completes
    # admission over the same raw object and only then receives a receipt.
    resent = _post_media(client, media, sidecar)
    assert resent.status_code == 200, resent.text
    assert len(all_raw_records()) == 1
    assert len(all_media_receipts()) == 1


def test_receipt_raw_ref_resolves_to_the_object_it_attests_to(client: TestClient) -> None:
    """A receipt's `raw_ref` must be the handle of the record actually written."""
    media = b"receipt-must-point-at-real-evidence"
    sidecar = _sidecar(media)
    admitted = _post_media(client, media, sidecar)
    assert admitted.status_code == 200, admitted.text

    record = all_raw_records()[0]
    representations = all_raw_representations(record.id)
    assert len(representations) == 1 and representations[0].active
    assert admitted.json()["raw_ref"] == raw_ref_for(record)
    queried = _get_receipts(client, sidecar["capture_id"]).json()["receipts"][0]
    assert queried["raw_ref"] == raw_ref_for(record)


def test_resend_after_retention_is_not_false_idempotent(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resend after erasure gets the explicit terminal outcome, never a replay ack."""
    media = b"retained-then-erased-media"
    sidecar = _sidecar(media)
    admitted = _post_media(client, media, sidecar)
    assert admitted.status_code == 200, admitted.text

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    write_settings_note(
        vault_root,
        SettingsNote(spec=SETTINGS, values={"retention_window_days": 1}),
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    enforce_hard_retention_bound(
        vault_root=vault_root, now=datetime.now(timezone.utc) + timedelta(days=2)
    )

    query = _get_receipts(client, sidecar["capture_id"])
    assert query.status_code == 200, query.text
    assert query.json()["receipts"][0]["outcome"] == "erased"

    def fail_if_meeting_side_effect_runs(**_: Any) -> None:
        pytest.fail("erased resend reached meeting side effects before returning 410")

    monkeypatch.setattr(
        media_ingress, "_ledger_session_segment", fail_if_meeting_side_effect_runs
    )
    resent = _post_media(client, media, sidecar)
    assert resent.status_code == 410, resent.text
    assert resent.json()["detail"] == {
        "error": "media_evidence_erased",
        "state": "erased",
        "capture_id": sidecar["capture_id"],
        "content_sha256": sidecar["content_sha256"],
        "trace_id": resent.json()["detail"]["trace_id"],
    }
    assert resent.json()["detail"]["trace_id"]
    assert len(all_raw_records()) == 0


def test_admitted_responses_carry_a_generation_bound_response_lease(
    client: TestClient,
) -> None:
    media = b"response-lease-shape"
    sidecar = _sidecar(media)

    first = _post_media(client, media, sidecar)
    replay = _post_media(client, media, sidecar)
    query = _get_receipts(client, sidecar["capture_id"])

    assert first.status_code == replay.status_code == query.status_code == 200
    first_lease = first.json()["response_lease"]
    replay_lease = replay.json()["response_lease"]
    query_lease = query.json()["receipts"][0]["response_lease"]
    assert first_lease["raw_ref"] == replay_lease["raw_ref"] == query_lease["raw_ref"]
    assert (
        first_lease["liveness_generation"]
        == replay_lease["liveness_generation"]
        == query_lease["liveness_generation"]
        == 1
    )
    assert (
        first_lease["lease_id"]
        == replay_lease["lease_id"]
        == query_lease["lease_id"]
    )
    assert (
        first_lease["expires_at"]
        == replay_lease["expires_at"]
        == query_lease["expires_at"]
    )
    assert replay.json()["idempotent_replay"] is True


def test_untombstoned_raw_absence_is_typed_unavailable_on_query_and_replay(
    client: TestClient,
) -> None:
    media = b"untombstoned-http-absence"
    sidecar = _sidecar(media)
    admitted = _post_media(client, media, sidecar)
    assert admitted.status_code == 200
    record = all_raw_records()[0]

    # Test-only corruption below the governed authority: public raw_store has
    # no deletion surface.
    assert raw_store._MEMORY_STORE.hard_delete(record.id)  # noqa: SLF001
    assert raw_liveness.all_deletion_tombstones() == []

    query = _get_receipts(client, sidecar["capture_id"])
    replay = _post_media(client, media, sidecar)
    for response in (query, replay):
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["error"] == "raw_liveness_unavailable"
        assert response.json()["detail"]["state"] == "unavailable"


def test_same_content_reinsertion_does_not_resurrect_old_receipt(
    client: TestClient, tmp_path: Path
) -> None:
    media = b"receipt-generation-reinsertion"
    old_sidecar = _sidecar(media)
    assert _post_media(client, media, old_sidecar).status_code == 200

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_retention_settings(vault_root)
    enforce_hard_retention_bound(
        vault_root=vault_root,
        now=datetime.now(timezone.utc) + timedelta(days=2),
        record_last_enforced=False,
    )

    new_sidecar = _sidecar(media)
    new = _post_media(client, media, new_sidecar)
    assert new.status_code == 200, new.text
    assert new.json()["response_lease"]["liveness_generation"] == 2

    answers = _get_receipts(
        client, old_sidecar["capture_id"], new_sidecar["capture_id"]
    )
    assert answers.status_code == 200, answers.text
    old_answer, new_answer = answers.json()["receipts"]
    assert old_answer["outcome"] == "erased"
    assert "response_lease" not in old_answer
    assert new_answer["outcome"] == "admitted"
    assert new_answer["response_lease"]["liveness_generation"] == 2
    assert old_answer["raw_ref"] != new_answer["raw_ref"]


def test_multiple_receipts_sharing_one_raw_identity_share_one_query_lease(
    client: TestClient,
) -> None:
    media = b"multiple-receipts-one-raw"
    first_sidecar = _sidecar(media)
    second_sidecar = _sidecar(media)
    assert _post_media(client, media, first_sidecar).status_code == 200
    assert _post_media(client, media, second_sidecar).status_code == 200

    response = _get_receipts(
        client, first_sidecar["capture_id"], second_sidecar["capture_id"]
    )
    assert response.status_code == 200, response.text
    first, second = response.json()["receipts"]
    assert first["raw_ref"] == second["raw_ref"]
    assert first["response_lease"] == second["response_lease"]


@pytest.mark.parametrize("producer", ["first", "replay", "query", "watched_folder"])
@pytest.mark.parametrize("writer", ["hard", "screen"])
def test_response_fence_serializes_every_producer_against_both_retention_writers(
    producer: str,
    writer: str,
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deterministic barrier proves all admitted producers converge on one fence."""

    media = f"barrier-{producer}-{writer}".encode()
    sidecar = _sidecar(media)
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_retention_settings(vault_root)

    if producer in {"replay", "query"}:
        initial = _post_media(client, media, sidecar)
        assert initial.status_code == 200, initial.text

    memo: Path | None = None
    if producer == "watched_folder":
        memo = tmp_path / "watched.m4a"
        memo.write_bytes(media)
        memo.with_name(f"{memo.name}.capture.json").write_text(
            json.dumps(
                {
                    "sidecar_version": 1,
                    "device_id": "iphone-barrier",
                    "capture_id": sidecar["capture_id"],
                }
            ),
            encoding="utf-8",
        )

    retention_time = datetime.now(timezone.utc) + timedelta(days=2)
    lease_appended = threading.Event()
    release_response = threading.Event()
    retention_at_fence = threading.Event()

    def mark_all_records_as_screen() -> None:
        with raw_store._MEMORY_STORE._lock:  # noqa: SLF001
            raw_store._MEMORY_STORE._rows = [  # noqa: SLF001
                replace(row, payload={**row.payload, "modality": "screen"})
                for row in raw_store._MEMORY_STORE._rows  # noqa: SLF001
            ]
            raw_store._MEMORY_STORE._by_identity = {  # noqa: SLF001
                row.content_identity: row
                for row in raw_store._MEMORY_STORE._rows  # noqa: SLF001
            }

    def response_hook(stage: str) -> None:
        assert stage == "after_lease_append"
        if writer == "screen":
            mark_all_records_as_screen()
        lease_appended.set()
        assert release_response.wait(timeout=5), "response barrier was never released"

    real_delete = raw_liveness.governed_delete_raw_record

    def deletion_at_fence(**kwargs: Any):
        retention_at_fence.set()
        return real_delete(**kwargs)

    monkeypatch.setattr(raw_liveness, "_utc_now", lambda: retention_time)
    monkeypatch.setattr(raw_liveness, "_response_lease_stage_hook", response_hook)
    monkeypatch.setattr(raw_liveness, "governed_delete_raw_record", deletion_at_fence)

    def produce():
        if producer in {"first", "replay"}:
            return _post_media(client, media, sidecar)
        if producer == "query":
            return _get_receipts(client, sidecar["capture_id"])
        assert memo is not None
        return admit_capture_file(memo, key=_KEY, stability_delay=0.0)

    def retain():
        if writer == "hard":
            return enforce_hard_retention_bound(
                vault_root=vault_root,
                now=retention_time,
                record_last_enforced=False,
            )
        return enforce_screen_frame_retention(
            vault_root=vault_root, now=retention_time
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        producer_future = executor.submit(produce)
        assert lease_appended.wait(timeout=5), "producer never reached response fence"
        retention_future = executor.submit(retain)
        assert retention_at_fence.wait(timeout=5), "retention never reached shared fence"
        assert not retention_future.done(), "retention crossed a held response fence"
        release_response.set()
        produced = producer_future.result(timeout=5)
        if writer == "hard":
            with pytest.raises(RetentionErasurePendingError, match="draining"):
                retention_future.result(timeout=5)
            retained = None
        else:
            retained = retention_future.result(timeout=5)

    if retained is not None:
        assert retained.deleted_count == 0
    assert len(all_raw_records()) == 1
    if producer == "watched_folder":
        assert produced.source_deleted is True
        assert memo is not None and not memo.exists()
        lease = raw_liveness._MEMORY.leases[-1]  # noqa: SLF001
    else:
        assert produced.status_code == 200, produced.text
        body = produced.json()
        lease_field = (
            body["receipts"][0]["response_lease"]
            if producer == "query"
            else body["response_lease"]
        )
        lease = raw_liveness._MEMORY.leases[-1]  # noqa: SLF001
        assert lease_field["lease_id"] == lease.lease_id

    expired = lease.expires_at + timedelta(microseconds=1)
    deleted = (
        enforce_hard_retention_bound(
            vault_root=vault_root, now=expired, record_last_enforced=False
        )
        if writer == "hard"
        else enforce_screen_frame_retention(vault_root=vault_root, now=expired)
    )
    assert deleted.deleted_count == 1
    erased = _get_receipts(client, sidecar["capture_id"])
    assert erased.status_code == 200
    assert erased.json()["receipts"][0]["outcome"] == "erased"
    assert "response_lease" not in erased.json()["receipts"][0]


def test_receipt_query_uses_one_batched_metadata_only_raw_lookup(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Receipt recovery never materializes ciphertext or opens one lookup per receipt."""
    first_media = b"metadata-only-receipt-query-one"
    second_media = b"metadata-only-receipt-query-two"
    first = _sidecar(first_media)
    second = _sidecar(second_media)
    assert _post_media(client, first_media, first).status_code == 200
    assert _post_media(client, second_media, second).status_code == 200

    calls: list[set[tuple[str, str]]] = []
    real_projection = media_ingress.raw_liveness.project_with_response_leases

    def metadata_lookup(
        requests: set[tuple[str, str]], *, now: datetime | None = None
    ) -> dict[str, media_ingress.raw_liveness.RawLivenessProjection]:
        calls.append(set(requests))
        return real_projection(requests, now=now)

    def unexpected_full_lookup(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("receipt recovery must not materialize a raw record")

    monkeypatch.setattr(
        media_ingress.raw_liveness,
        "project_with_response_leases",
        metadata_lookup,
    )
    monkeypatch.setattr(
        media_ingress.raw_store,
        "get_raw_record_by_content_identity",
        unexpected_full_lookup,
    )

    response = _get_receipts(client, first["capture_id"], second["capture_id"])
    assert response.status_code == 200, response.text
    assert [item["outcome"] for item in response.json()["receipts"]] == ["admitted", "admitted"]
    receipt_by_hash = {
        receipt.content_sha256: receipt for receipt in all_media_receipts()
    }
    assert calls == [
        {
            (
                receipt_by_hash[first["content_sha256"]].raw_ref,
                first["content_sha256"],
            ),
            (
                receipt_by_hash[second["content_sha256"]].raw_ref,
                second["content_sha256"],
            ),
        }
    ]


def test_receipt_query_reports_raw_state_lookup_failure_as_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raw-state backend failure is 503, never a false answer or unnamed 500."""
    media = b"raw-state-lookup-unavailable"
    sidecar = _sidecar(media)
    assert _post_media(client, media, sidecar).status_code == 200

    def unavailable(
        _requests: set[tuple[str, str]], *, now: datetime | None = None
    ) -> dict[str, media_ingress.raw_liveness.RawLivenessProjection]:
        del now
        raise media_ingress.raw_liveness.RawLivenessUnavailableError(
            "raw metadata store unavailable"
        )

    monkeypatch.setattr(
        media_ingress.raw_liveness,
        "project_with_response_leases",
        unavailable,
    )

    response = _get_receipts(client, sidecar["capture_id"])
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["error"] == "raw_liveness_unavailable"
    assert response.json()["detail"]["state"] == "unavailable"
    assert response.json()["detail"]["trace_id"]


def test_pending_cold_erasure_is_public_503_not_a_new_receipt_outcome(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = b"pending-cold-erasure-public-contract"
    sidecar = _sidecar(media)
    assert _post_media(client, media, sidecar).status_code == 200
    record = all_raw_records()[0]
    generation = raw_liveness._MEMORY.generations_by_record[record.id]  # noqa: SLF001

    def pending(
        requests: set[tuple[str, str]], *, now: datetime | None = None
    ) -> dict[str, raw_liveness.RawLivenessProjection]:
        del now
        return {
            raw_ref: raw_liveness.RawLivenessProjection(
                outcome="erasure_pending",
                generation=generation,
            )
            for raw_ref, _content_identity in requests
        }

    monkeypatch.setattr(raw_liveness, "project_with_response_leases", pending)

    query = _get_receipts(client, sidecar["capture_id"])
    replay = _post_media(client, media, sidecar)
    for response in (query, replay):
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["error"] == "raw_liveness_unavailable"
        assert response.json()["detail"]["state"] == "unavailable"


def test_receipt_identity_includes_the_capture_id(client: TestClient) -> None:
    """INV-CDLM-3's identity is the *pair*, so identical bytes do not share a receipt.

    Two clients that capture byte-identical content share one raw object but each
    needs its own answer to "was my capture accepted?". A receipt identity derived
    from the hash alone would hand the second client the first one's receipt and
    answer `unknown` for its own id forever.
    """
    media = b"byte-identical-content-from-two-captures"
    first_sidecar = _sidecar(media)
    second_sidecar = _sidecar(media)
    assert first_sidecar["capture_id"] != second_sidecar["capture_id"]

    first = _post_media(client, media, first_sidecar)
    second = _post_media(client, media, second_sidecar)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["receipt_id"] != second.json()["receipt_id"]
    assert second.json().get("idempotent_replay") is not True

    # One object per content hash, one receipt per transfer identity.
    assert len(all_raw_records()) == 1
    assert len(all_media_receipts()) == 2
    for sidecar in (first_sidecar, second_sidecar):
        answer = _get_receipts(client, sidecar["capture_id"]).json()["receipts"][0]
        assert answer["outcome"] == "admitted"
        assert answer["capture_id"] == sidecar["capture_id"]


def test_capture_id_spelling_does_not_mint_a_second_receipt(client: TestClient) -> None:
    """One logical UUID is one transfer identity, on admission AND on recovery.

    `UUID()` accepts uppercase, braced, unhyphenated, and `urn:uuid:` forms of the
    same id, and the receipt identity is derived from this string. Canonicalizing
    only on the write path is worse than not canonicalizing at all: an uppercase
    client (Swift's `UUID().uuidString`) would be told `unknown` for a capture
    that IS durably admitted — precisely the reconnect answer it cannot verify any
    other way, and the one case where it does not know the canonical form because
    the response was lost.
    """
    canonical = str(uuid4())
    spellings = [
        canonical,
        canonical.upper(),
        "{" + canonical + "}",
        canonical.replace("-", ""),
        f"urn:uuid:{canonical}",
    ]

    media = b"same-capture-id-many-spellings"
    first = _post_media(client, media, _sidecar(media, capture_id=canonical))
    assert first.status_code == 200, first.text

    for spelling in spellings:
        resent = _post_media(client, media, _sidecar(media, capture_id=spelling))
        assert resent.status_code == 200, resent.text
        assert resent.json()["receipt_id"] == first.json()["receipt_id"]
        assert resent.json()["idempotent_replay"] is True

        answer = _get_receipts(client, spelling).json()["receipts"][0]
        assert answer["outcome"] == "admitted", f"{spelling} queried as {answer['outcome']}"
        assert answer["receipt_id"] == first.json()["receipt_id"]
        # The answer echoes what the client asked, so it stays alignable.
        assert answer["capture_id"] == spelling

    assert len(all_media_receipts()) == 1
    assert len(all_raw_records()) == 1


def test_one_capture_id_spans_both_lanes(client: TestClient, tmp_path: Path) -> None:
    """The sidecar's `capture_id` is why a client can query one id across lanes.

    A watched-folder admission keyed on a differently-spelled UUID must not mint a
    second receipt identity for content the governed lane then re-sends.
    """
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()
    memo = watch_dir / "memo-cross-lane.m4a"
    payload = b"admitted-by-the-watcher-then-resent-over-http"
    memo.write_bytes(payload)
    canonical = str(uuid4())
    memo.with_name(f"{memo.name}.capture.json").write_text(
        json.dumps(
            {"sidecar_version": 1, "device_id": "iphone-1", "capture_id": canonical.upper()}
        ),
        encoding="utf-8",
    )
    assert admit_capture_file(memo, key=_KEY, stability_delay=0.0).created

    resent = _post_media(client, payload, _sidecar(payload, capture_id=canonical))
    assert resent.status_code == 200, resent.text
    assert resent.json()["idempotent_replay"] is True
    assert len(all_media_receipts()) == 1
    assert _get_receipts(client, canonical).json()["receipts"][0]["outcome"] == "admitted"


def test_consent_refusal_admits_nothing(client: TestClient) -> None:
    """HEIM-3 is the one signal->raw gate, and its refusal is a named 409.

    Follows this lane's own consent scope since #4492: revoking the
    media-capture grant is what refuses media ingress. Revoking the voice-memo
    grant no longer does — that separation is
    `test_media_and_voice_memo_grants_revoke_independently`.
    """
    revoke_consent(grant_ref=MEDIA_CAPTURE_GRANT_REF, revoked_by="test-operator")

    media = b"no-active-grant-covers-this"
    refused = _post_media(client, media, _sidecar(media))
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["error"] == "consent_refused"
    assert detail["state"] == "not_acknowledged"
    assert all_raw_records() == []
    assert all_media_receipts() == []


# ---------------------------------------------------------------------------
# #4492: the lane's own consent scope, naming every admitted modality
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["audio", "image", "video", "document"])
def test_admitted_media_stamps_the_media_capture_grant(client: TestClient, kind: str) -> None:
    """Every admitted kind is stamped with a grant whose profile names that kind.

    This is the defect `KD-4E7228960927` recorded: a photo, video, or document
    raw record carried a consent block pointing at the voice-memo grant, whose
    `capture_profile.modalities` is `["speech"]`. Asserted on the durable raw
    record written by the production route, not on the seam's return value.
    """
    media = f"admitted-{kind}-bytes".encode()
    admitted = _post_media(client, media, _sidecar(media, kind=kind))
    assert admitted.status_code == 200, admitted.text

    records = all_raw_records()
    assert len(records) == 1
    consent = records[0].consent
    assert consent["grant_ref"] == MEDIA_CAPTURE_GRANT_REF
    assert consent["grant_ref"] != SELF_RECORD_GRANT_REF

    # The grant the record points at actually covers what was captured.
    grant = resolve_active_grant(scope=MEDIA_CAPTURE_SCOPE)
    assert grant is not None and grant.grant_ref == consent["grant_ref"]
    assert kind in grant.capture_profile["modalities"]


def test_media_and_voice_memo_grants_revoke_independently(
    client: TestClient, tmp_path: Path
) -> None:
    """Two lanes, two grants: revoking one must not disable the other.

    Before #4492 both lanes resolved `SELF_RECORD_SCOPE`, so consenting to
    voice memos also consented to photo/video/document ingress from any device
    — and revoking voice memos silently killed media ingress.
    """
    # 1. Revoking the voice-memo grant leaves the governed media lane admitting.
    revoke_consent(grant_ref=SELF_RECORD_GRANT_REF, revoked_by="test-operator")
    media = b"media-ingress-survives-voice-memo-revocation"
    admitted = _post_media(client, media, _sidecar(media))
    assert admitted.status_code == 200, admitted.text
    assert admitted.json()["outcome"] == "admitted"

    # ...while the watched-folder lane, which still admits under the voice-memo
    # grant, is correctly refused by that same revocation.
    watch_dir = tmp_path / "watched-refused"
    watch_dir.mkdir()
    memo = watch_dir / "memo-after-revocation.m4a"
    memo.write_bytes(b"a voice memo after the voice-memo grant was revoked")
    with pytest.raises(ConsentRefusedError):
        admit_capture_file(memo, key=_KEY, stability_delay=0.0)

    # 2. The mirror image: revoking only the media grant leaves the
    #    watched-folder lane admitting.
    reset_memory_consent_ledger()
    reset_memory_raw_store()
    reset_memory_media_receipts()
    revoke_consent(grant_ref=MEDIA_CAPTURE_GRANT_REF, revoked_by="test-operator")

    watched = tmp_path / "watched-admitted"
    watched.mkdir()
    surviving = watched / "memo-survives.m4a"
    surviving.write_bytes(b"a voice memo after the media grant was revoked")
    result = admit_capture_file(surviving, key=_KEY, stability_delay=0.0)
    assert result.created
    assert result.record.consent["grant_ref"] == SELF_RECORD_GRANT_REF

    refused_media = b"media-ingress-is-the-one-that-stops"
    refused = _post_media(client, refused_media, _sidecar(refused_media))
    assert refused.status_code == 409
    assert refused.json()["detail"]["error"] == "consent_refused"


def test_capture_profile_is_not_an_enforcement_gate(client: TestClient) -> None:
    """`capture_profile` stays descriptive: no admission path reads it as a gate.

    The defect was rated P2 rather than an authority-integrity P1 precisely
    because nothing compares a modality against `capture_profile`, and #4492
    must not quietly change that — introducing modality enforcement would be a
    new gate with no contract demand behind it. Proven by narrowing the active
    grant's profile to a modality the request does not use and asserting the
    admission still succeeds.
    """
    from app.heimdal.consent_ledger import grant_consent

    # A later grant on the same scope wins (last-appended-wins), so this is the
    # profile the admission resolves — and it names nothing the request sends.
    revoke_consent(grant_ref=MEDIA_CAPTURE_GRANT_REF, revoked_by="test-operator")
    grant_consent(
        grant_ref="grant-media-capture-narrowed-profile",
        basis="self_record",
        scope=MEDIA_CAPTURE_SCOPE,
        granted_by="operator",
        capture_profile={"modalities": ["semaphore"], "degradation_rules": []},
    )

    media = b"an image admitted under a profile that names only semaphore"
    admitted = _post_media(client, media, _sidecar(media, kind="image"))
    assert admitted.status_code == 200, (
        "capture_profile must remain descriptive; a mismatch is a provenance "
        "concern, not an admission gate this slice may introduce"
    )
    records = all_raw_records()
    assert len(records) == 1
    assert records[0].consent["grant_ref"] == "grant-media-capture-narrowed-profile"


def test_unregistered_sensor_admits_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T5: an unregistered adapter identity cannot admit raw evidence.

    `raw_store.insert_raw_record` only requires a non-empty sensor dict, so this
    assert is the lane's only registration check.
    """
    monkeypatch.setattr(
        media_ingress.capture_adapter, "is_sensor_registered", lambda *_a, **_k: False
    )
    media = b"admitted-by-an-unregistered-adapter"
    refused = _post_media(client, media, _sidecar(media))
    assert refused.status_code == 500
    assert refused.json()["detail"]["state"] == "not_acknowledged"
    assert all_raw_records() == []
    assert all_media_receipts() == []


# ---------------------------------------------------------------------------
# AC2: end-to-end idempotency on (capture_id, content_sha256)
# ---------------------------------------------------------------------------


def test_resend_is_idempotent_end_to_end(client: TestClient, _memory_runtime: Path) -> None:
    media = b"one-segment-of-audio"
    sidecar = _sidecar(media)

    first = _post_media(client, media, sidecar)
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body.get("idempotent_replay") is not True

    # The client never saw the first response (lost response / reconnect) and
    # resends the identical (capture_id, content_sha256) pair.
    second = _post_media(client, media, sidecar)
    assert second.status_code == 200, second.text
    second_body = second.json()

    assert second_body["receipt_id"] == first_body["receipt_id"]
    assert second_body["raw_ref"] == first_body["raw_ref"]
    assert second_body["admitted_at"] == first_body["admitted_at"]
    assert second_body["idempotent_replay"] is True

    assert len(all_raw_records()) == 1
    assert len(all_media_receipts()) == 1
    assert len(_admitted_events(_memory_runtime)) == 1


# ---------------------------------------------------------------------------
# AC3: per-kind caps, lineage metadata, and the named error states
# ---------------------------------------------------------------------------


def test_kind_caps_and_named_error_states(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, _memory_runtime: Path
) -> None:
    # Every configured kind admits within its cap and lands with lineage.
    for index, kind in enumerate(media_ingress.MEDIA_KINDS):
        media = f"payload-for-{kind}".encode()
        sidecar = _sidecar(media, kind=kind, device_id=f"device-{index}")
        response = _post_media(client, media, sidecar)
        assert response.status_code == 200, response.text
        record = next(row for row in all_raw_records() if row.content_identity == sidecar["content_sha256"])
        assert record.payload["kind"] == kind
        assert record.payload["capture_id"] == sidecar["capture_id"]
        assert record.payload["device_id"] == f"device-{index}"
        assert record.payload["captured_at"] == sidecar["captured_at"]
        assert record.payload["schema_version"] == 1
        assert record.payload["lane"] == media_ingress.LANE_MEDIA_INGRESS

    admitted_raw = len(all_raw_records())
    admitted_receipts = len(all_media_receipts())
    assert admitted_raw == len(media_ingress.MEDIA_KINDS)

    # Hash mismatch -> 422, nothing admitted.
    media = b"bytes-that-do-not-match"
    mismatch = _post_media(client, media, _sidecar(media, content_sha256="0" * 64))
    assert mismatch.status_code == 422
    assert mismatch.json()["detail"]["error"] == "content_hash_mismatch"

    # Sidecar schema violations -> 422, nothing admitted. Both shapes are
    # covered: a missing field (rejected by pydantic itself) and every
    # custom-validator rejection. The latter must be asserted separately —
    # pydantic attaches the raising exception to each error's `ctx`, so a
    # response that carries the error list verbatim fails to encode and degrades
    # into a bare 500 for exactly these inputs while a missing-field test stays
    # green over the break.
    incomplete = _sidecar(media)
    incomplete.pop("device_id")
    for invalid in (
        incomplete,
        _sidecar(media, capture_id="not-a-uuid"),
        _sidecar(media, content_sha256="abc"),
        _sidecar(media, captured_at="yesterday"),
        _sidecar(media, schema_version=2),
    ):
        schema_violation = _post_media(client, media, invalid)
        assert schema_violation.status_code == 422, schema_violation.text
        assert schema_violation.headers["content-type"].startswith("application/json")
        assert schema_violation.json()["detail"]["error"] == "sidecar_schema_invalid"

    # Unsupported kind -> 415, nothing admitted.
    unsupported = _post_media(client, media, _sidecar(media, kind="hologram"))
    assert unsupported.status_code == 415
    assert unsupported.json()["detail"]["error"] == "unsupported_media_kind"

    # Over the configured per-kind cap -> 413, nothing admitted.
    monkeypatch.setenv("HEIMDAL_MEDIA_MAX_BYTES_IMAGE", "8")
    oversize_media = b"x" * 64
    oversize = _post_media(client, oversize_media, _sidecar(oversize_media, kind="image"))
    assert oversize.status_code == 413
    oversize_detail = oversize.json()["detail"]
    assert oversize_detail["error"] == "media_too_large"
    assert oversize_detail["max_bytes"] == 8

    # "nothing admitted" is asserted for the whole error set at once: no raw
    # object and no receipt was created by any of the four refusals.
    assert len(all_raw_records()) == admitted_raw
    assert len(all_media_receipts()) == admitted_receipts


# ---------------------------------------------------------------------------
# AC4: the receipt query is the reconnect/recovery answer
# ---------------------------------------------------------------------------


def test_receipt_query_answers_recovery(client: TestClient) -> None:
    media = b"admitted-then-queried"
    sidecar = _sidecar(media)
    admitted = _post_media(client, media, sidecar)
    assert admitted.status_code == 200, admitted.text
    receipt_id = admitted.json()["receipt_id"]

    never_seen = str(uuid4())
    response = _get_receipts(client, sidecar["capture_id"], never_seen)
    assert response.status_code == 200, response.text
    receipts = response.json()["receipts"]

    # Answers stay positionally aligned with the requested ids so a client can
    # reconcile its own queue without re-matching.
    assert [entry["capture_id"] for entry in receipts] == [sidecar["capture_id"], never_seen]
    assert receipts[0]["outcome"] == "admitted"
    assert receipts[0]["receipt_id"] == receipt_id
    assert receipts[0]["content_sha256"] == sidecar["content_sha256"]
    assert receipts[0]["raw_ref"] and receipts[0]["admitted_at"]
    assert receipts[1] == {"capture_id": never_seen, "outcome": "unknown"}

    # The batch is bounded, and an id-less query is a named refusal rather
    # than an unbounded table read.
    assert _get_receipts(client).status_code == 422
    too_many = _get_receipts(client, *[str(uuid4()) for _ in range(media_ingress.RECEIPT_QUERY_MAX_IDS + 1)])
    assert too_many.status_code == 422
    assert too_many.json()["detail"]["error"] == "too_many_capture_ids"


# ---------------------------------------------------------------------------
# AC5: the watched-folder lane shares the receipt seam
# ---------------------------------------------------------------------------


def test_watched_folder_admission_shares_receipt_seam(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _memory_runtime: Path
) -> None:
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()

    # The legacy lane runs through the same acknowledgement seam, so it owes the
    # same ordering: event committed before the receipt exists. Asserted here and
    # not only on the HTTP lane, or an inversion on this lane would go unseen.
    order: list[str] = []
    real_commit = media_ingress.outbox_service.append_jsonl_outbox_event
    real_receipt_write = media_ingress.media_receipts.append_media_receipt
    monkeypatch.setattr(
        media_ingress.outbox_service,
        "append_jsonl_outbox_event",
        lambda *a, **k: (order.append("event-commit"), real_commit(*a, **k))[1],
    )
    monkeypatch.setattr(
        media_ingress.media_receipts,
        "append_media_receipt",
        lambda **k: (order.append("receipt-write"), real_receipt_write(**k))[1],
    )

    # (a) sidecar supplies a capture_id -> the receipt is keyed by it.
    with_sidecar = watch_dir / "memo-with-sidecar.m4a"
    with_sidecar.write_bytes(b"watched-folder-memo-one")
    capture_id = str(uuid4())
    with_sidecar.with_name(f"{with_sidecar.name}.capture.json").write_text(
        json.dumps(
            {
                "sidecar_version": 1,
                "device_id": "iphone-1",
                "capture_id": capture_id,
                "recorded_start_at": "2026-07-29T11:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    result = admit_capture_file(with_sidecar, key=_KEY, stability_delay=0.0)
    assert result.created

    answered = _get_receipts(client, capture_id).json()["receipts"][0]
    assert answered["outcome"] == "admitted"
    assert answered["content_sha256"] == result.record.content_identity
    assert answered["lane"] == media_ingress.LANE_WATCHED_FOLDER

    # (b) no sidecar capture_id -> the receipt is keyed by the content hash,
    # which is what the query accepts for the legacy lane.
    plain = watch_dir / "memo-plain.m4a"
    plain.write_bytes(b"watched-folder-memo-two")
    plain_result = admit_capture_file(plain, key=_KEY, stability_delay=0.0)
    assert plain_result.created
    content_hash = plain_result.record.content_identity

    hash_keyed = _get_receipts(client, content_hash).json()["receipts"][0]
    assert hash_keyed["outcome"] == "admitted"
    assert hash_keyed["capture_id"] == content_hash
    assert hash_keyed["content_sha256"] == content_hash

    assert len(_admitted_events(_memory_runtime)) == 2
    assert order == ["event-commit", "receipt-write"] * 2


def test_watched_folder_replay_emits_no_further_admission_event(
    tmp_path: Path, _memory_runtime: Path
) -> None:
    """A re-admitted watched-folder file must not emit an event per watch tick.

    `_delete_source_file` logs rather than raises, so a memo whose delete fails
    stays in the folder and is re-admitted on every tick. The raw store is
    idempotent by content hash, so without a replay guard in the shared
    acknowledgement seam that one file would emit an unbounded number of
    admission events against a single receipt — and CDLM-02/CDLM-06 would
    double-count it.
    """
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()
    memo = watch_dir / "sticky-memo.m4a"
    memo.write_bytes(b"a memo whose source delete keeps failing")

    for tick in range(4):
        memo.write_bytes(b"a memo whose source delete keeps failing")
        result = admit_capture_file(memo, key=_KEY, stability_delay=0.0)
        assert result.created is (tick == 0)

    assert len(all_raw_records()) == 1
    assert len(all_media_receipts()) == 1
    assert len(_admitted_events(_memory_runtime)) == 1


def test_watched_folder_sidecar_capture_id_of_the_wrong_type_is_not_a_new_failure_mode(
    client: TestClient, tmp_path: Path
) -> None:
    """A malformed sidecar value must degrade, never break the legacy lane.

    Sidecar values are untrusted and not type-validated upstream, and the receipt
    call runs *after* the durable write and before delete-after-confirmed-ingest.
    An exception escaping there would leave the memo admitted but undeleted and
    "refused" on every later tick.
    """
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()
    memo = watch_dir / "memo-bad-sidecar.m4a"
    memo.write_bytes(b"watched-folder-memo-with-a-numeric-capture-id")
    memo.with_name(f"{memo.name}.capture.json").write_text(
        json.dumps({"sidecar_version": 1, "device_id": "iphone-1", "capture_id": 12345}),
        encoding="utf-8",
    )

    result = admit_capture_file(memo, key=_KEY, stability_delay=0.0)

    assert result.created and result.source_deleted
    assert not memo.exists()
    # The receipt falls back to the content-hash key rather than being lost.
    content_hash = result.record.content_identity
    answered = _get_receipts(client, content_hash).json()["receipts"][0]
    assert answered["outcome"] == "admitted"
    assert answered["capture_id"] == content_hash


# ---------------------------------------------------------------------------
# AC6: LAN/loopback/tailnet posture only -- no public ingress
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "peer",
    [
        "192.168.1.20",
        "100.101.102.103",  # tailnet CGNAT
        "10.0.0.5",
        "fd7a:115c:a1e0::1",  # tailnet ULA
        "::ffff:192.168.1.20",  # a dual-stack listener's view of an IPv4 LAN peer
    ],
)
def test_ingress_admits_lan_loopback_and_tailnet_peers(peer: str) -> None:
    """The refusal below is specific to public peers, not a blanket refusal."""
    lan_client = TestClient(app, client=(peer, 41000))
    media = f"admitted-from-{peer}".encode()
    assert _post_media(lan_client, media, _sidecar(media)).status_code == 200


@pytest.mark.parametrize("peer", ["203.0.113.7", "8.8.8.8", "2001:db8::1", ""])
def test_ingress_refuses_peers_it_cannot_place_inside_the_posture(peer: str) -> None:
    """A public peer *and* an unidentifiable one both fail closed.

    An empty host is not provably inside the posture, so it is refused rather
    than treated as loopback the way the general-purpose auth helper does.
    """
    outside = TestClient(app, client=(peer, 41000))
    media = f"never-admitted-from-{peer}".encode()
    response = _post_media(outside, media, _sidecar(media))
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "public_ingress_refused"
    assert all_raw_records() == []


def test_media_over_every_cap_is_refused_before_the_kind_is_known(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The coarse bound limits resident memory before any per-kind cap applies."""
    for kind in media_ingress.MEDIA_KINDS:
        monkeypatch.setenv(f"HEIMDAL_MEDIA_MAX_BYTES_{kind.upper()}", "16")
    oversize = b"y" * 128
    response = _post_media(client, oversize, _sidecar(oversize, kind="video"))
    assert response.status_code == 413
    detail = response.json()["detail"]
    assert detail["error"] == "media_too_large"
    assert detail["max_bytes"] == 16
    assert all_raw_records() == []


@pytest.mark.asyncio
async def test_part_read_is_bounded_rather_than_slurped() -> None:
    """The part read passes its bound down, so resident memory is actually capped.

    Asserted on `_part_bytes` directly: "how many bytes reached memory" has no
    black-box signal — an unbounded read produces the identical 413 — so the
    bound is pinned where it is owned.
    """
    from app.api.routes import heimdal_capture

    requested: list[int | None] = []

    class _RecordingPart(UploadFile):
        def __init__(self) -> None:
            super().__init__(file=io.BytesIO(b"z" * 4096), filename="big.bin")

        async def read(self, size: int = -1) -> bytes:  # type: ignore[override]
            requested.append(size)
            return b"z" * (size if size and size > 0 else 4096)

    with pytest.raises(HTTPException) as refusal:
        await heimdal_capture._part_bytes("media", _RecordingPart(), "t-bound", max_bytes=64)

    assert requested == [65]
    assert refusal.value.status_code == 413
    assert refusal.value.detail["max_bytes"] == 64


def test_unusable_per_kind_cap_override_is_a_named_refusal(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An override on *any* kind must be named, not an unnamed 500.

    The coarse bound resolves every kind, so a bad override on a kind the request
    does not even use is still reached — and must still be branchable.
    """
    monkeypatch.setenv("HEIMDAL_MEDIA_MAX_BYTES_VIDEO", "not-a-number")
    media = b"audio-post-with-a-broken-video-cap"
    response = _post_media(client, media, _sidecar(media, kind="audio"))
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["error"] == "media_cap_misconfigured"
    assert detail["state"] == "not_acknowledged"
    assert "HEIMDAL_MEDIA_MAX_BYTES_VIDEO" in detail["message"]
    assert all_raw_records() == []

    monkeypatch.setenv("HEIMDAL_MEDIA_MAX_BYTES_VIDEO", "0")
    zero_cap = _post_media(client, media, _sidecar(media, kind="audio"))
    assert zero_cap.status_code == 500
    assert zero_cap.json()["detail"]["error"] == "media_cap_misconfigured"


def test_ingress_refuses_public_binding(client: TestClient) -> None:
    public_client = TestClient(app, client=("203.0.113.7", 41000))
    media = b"never-admitted-from-the-public-internet"
    sidecar = _sidecar(media)

    refused = _post_media(public_client, media, sidecar)
    assert refused.status_code == 403
    assert refused.json()["detail"]["error"] == "public_ingress_refused"

    # The posture is judged on the immediate peer only. Honouring a forwarded
    # header here would let any public caller behind a relay assert a local
    # address — exactly the ingress this slice must not open.
    spoofed = _post_media(
        public_client, media, sidecar, headers={"x-forwarded-for": "127.0.0.1"}
    )
    assert spoofed.status_code == 403
    assert spoofed.json()["detail"]["error"] == "public_ingress_refused"
    spoofed_query = client.get(
        "/api/heimdal/capture/receipts",
        params=[("capture_id", sidecar["capture_id"])],
        headers={"x-forwarded-for": "203.0.113.7"},
    )
    # ...and a *loopback* caller is not demoted by a forwarded header either.
    assert spoofed_query.status_code == 200

    # The receipt query discloses admission state, so it carries the same posture.
    refused_query = _get_receipts(public_client, sidecar["capture_id"])
    assert refused_query.status_code == 403
    assert refused_query.json()["detail"]["error"] == "public_ingress_refused"

    # Nothing was admitted, and the loopback client agrees it never arrived.
    assert all_raw_records() == []
    assert all_media_receipts() == []
    assert _get_receipts(client, sidecar["capture_id"]).json()["receipts"][0]["outcome"] == "unknown"


def test_no_reachable_failure_returns_an_unnamed_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"Never blind-retryable" only holds if every failure carries a branchable `error`.

    Two failures that bypass the specific handlers: the raw-store key precondition
    (resolved before the guarded raw write) and an arbitrary store fault.
    """
    monkeypatch.delenv("HEIMDAL_RAW_STORE_KEY", raising=False)
    media = b"cannot-be-encrypted-without-a-key"
    keyless = _post_media(client, media, _sidecar(media))
    assert keyless.status_code == 500
    keyless_detail = keyless.json()["detail"]
    assert keyless_detail["error"] == "raw_store_key_unavailable"
    assert keyless_detail["state"] == "not_acknowledged"

    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())

    def exploding_lookup(*_args: Any, **_kwargs: Any):
        raise TimeoutError("receipt store went away mid-admission")

    monkeypatch.setattr(media_ingress.media_receipts, "get_media_receipt", exploding_lookup)
    other = b"an-unexpected-store-fault"
    unexpected = _post_media(client, other, _sidecar(other))
    assert unexpected.status_code == 500
    unexpected_detail = unexpected.json()["detail"]
    assert unexpected_detail["error"] == "admission_failed"
    assert unexpected_detail["state"] == "not_acknowledged"
    assert all_media_receipts() == []

    # A receipt-store read failure must never be answered as `unknown`: a client
    # deletes originals against that answer.
    monkeypatch.setattr(
        media_receipts, "find_media_receipts_by_capture_ids", exploding_lookup
    )
    degraded = _get_receipts(client, str(uuid4()))
    assert degraded.status_code == 503
    assert degraded.json()["detail"]["error"] == "receipt_store_unavailable"


def test_committed_db_outbox_event_is_not_reread_as_uncommitted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A derived idempotency key makes an ON CONFLICT no-op *proof of commit*.

    `write_outbox_event` returns "" when its ON CONFLICT swallowed a duplicate.
    Because this lane's key is derived from the transfer identity (unlike the
    governed text capture's random event_id), treating "" as "not committed"
    would refuse an already-committed capture forever.

    Reaching the DB sink branch takes one more fake than it used to. Since
    #4064/#4203 the self-owned outbox policy SKIPS an optional write under an
    explicit memory backend, so `STORE_BACKEND=memory` plus a DSN no longer
    runs the write at all — and `_emit_admission_event` now refuses to read
    that skip as a commit (#4214), because a `""` from a write that never ran
    is not proof of anything. The receipt store stays memory-backed, so this
    test keeps `STORE_BACKEND=memory` and instead states the runtime it is
    simulating outright: a runtime where the self-owned write DOES connect.
    That is the only configuration in which this test's claim — a derived-key
    ON CONFLICT no-op is proof of commit — is meaningful.

    The real skip behaviour is pinned separately by
    `tests/heimdal/test_meeting_emitters_skip_reporting.py` and
    `tests/services/test_outbox_memory_mode.py`. No real connection is opened
    here; `write_outbox_event` is faked below.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://unused:unused@db.invalid:5432/none")
    monkeypatch.setattr(
        media_ingress.outbox_service, "self_owned_write_would_skip", lambda **_kwargs: False
    )

    def conflict_noop(*_args: Any, **_kwargs: Any) -> str:
        return ""

    def unwritable_jsonl(*_args: Any, **_kwargs: Any) -> bool:
        raise OSError("jsonl sink unavailable")

    monkeypatch.setattr(media_ingress.outbox_service, "write_outbox_event", conflict_noop)
    monkeypatch.setattr(
        media_ingress.outbox_service, "append_jsonl_outbox_event", unwritable_jsonl
    )

    media = b"already-committed-on-a-prior-attempt"
    admitted = _post_media(client, media, _sidecar(media))
    assert admitted.status_code == 200, admitted.text
    assert len(all_media_receipts()) == 1

    # A genuine sink failure (both sinks raising) still refuses to acknowledge.
    def exploding_db(*_args: Any, **_kwargs: Any) -> str:
        raise OSError("db outbox unavailable")

    monkeypatch.setattr(media_ingress.outbox_service, "write_outbox_event", exploding_db)
    other = b"neither-sink-accepted-this-one"
    refused = _post_media(client, other, _sidecar(other))
    assert refused.status_code == 500
    assert refused.json()["detail"]["error"] == "admission_event_commit_failed"
    assert len(all_media_receipts()) == 1


def test_media_receipt_store_rejects_a_second_receipt_for_the_same_identity() -> None:
    """The receipt identity is `(capture_id, content_sha256)`, storage-enforced."""
    capture_id = str(uuid4())
    content_sha256 = hashlib.sha256(b"identity-bytes").hexdigest()
    first, created = media_receipts.append_media_receipt(
        capture_id=capture_id,
        content_sha256=content_sha256,
        raw_ref="heimraw:record-1",
        kind="audio",
        lane=media_ingress.LANE_MEDIA_INGRESS,
        trace_id="t-1",
        payload={},
    )
    assert created
    second, created_again = media_receipts.append_media_receipt(
        capture_id=capture_id,
        content_sha256=content_sha256,
        raw_ref="heimraw:record-1",
        kind="audio",
        lane=media_ingress.LANE_MEDIA_INGRESS,
        trace_id="t-2",
        payload={},
    )
    assert not created_again
    assert second.receipt_id == first.receipt_id
    assert second.admitted_at == first.admitted_at
    assert len(all_media_receipts()) == 1


@pytest.mark.parametrize(
    "spelling",
    ["upper", "braced", "unhyphenated", "urn", "padded"],
)
def test_receipt_identity_is_spelling_independent_in_the_store(spelling: str) -> None:
    """The store owns canonicalization, so it holds regardless of the caller.

    Asserted directly on `media_receipts`, not only through the route: this is the
    rule every lane and every lookup depends on, and it must not rest on a
    particular caller normalizing first.
    """
    canonical = str(uuid4())
    variants = {
        "upper": canonical.upper(),
        "braced": "{" + canonical + "}",
        "unhyphenated": canonical.replace("-", ""),
        "urn": f"urn:uuid:{canonical}",
        "padded": f"  {canonical}  ",
    }
    variant = variants[spelling]
    content_sha256 = hashlib.sha256(f"identity-{spelling}".encode()).hexdigest()

    assert media_receipts.canonical_capture_id(variant) == canonical
    assert media_receipts.derive_receipt_id(variant, content_sha256) == (
        media_receipts.derive_receipt_id(canonical, content_sha256)
    )

    stored, created = media_receipts.append_media_receipt(
        capture_id=variant,
        content_sha256=content_sha256,
        raw_ref="heimraw:record-spelling",
        kind="audio",
        lane=media_ingress.LANE_MEDIA_INGRESS,
        payload={},
    )
    assert created and stored.capture_id == canonical
    assert media_receipts.get_media_receipt(canonical, content_sha256) is not None
    # Both spellings resolve, and each answer is keyed back by what was asked.
    found = media_receipts.find_media_receipts_by_capture_ids([variant, canonical])
    assert set(found) == {variant, canonical}
    assert {receipt.receipt_id for receipt in found.values()} == {stored.receipt_id}

    # A non-UUID id (the watched-folder lane's content-hash key) passes through.
    assert media_receipts.canonical_capture_id(content_sha256) == content_sha256


def test_shared_seam_reports_an_already_acknowledged_identity_as_not_new() -> None:
    """`record_media_admission` tells its caller whether *it* acknowledged.

    This is what lets `idempotent_replay` stay truthful when a concurrent request
    won the race between the pre-write short-circuit and the seam's own guard.
    """
    capture_id = str(uuid4())
    media = b"seam-guard-bytes"
    content_sha256 = hashlib.sha256(media).hexdigest()
    ciphertext, nonce = encrypt_raw_bytes(media, key=_KEY)
    record, created = insert_raw_record(
        content_identity=content_sha256,
        capture_chain=["test"],
        sensor={"sensor_id": "test"},
        consent={"grant_ref": "test"},
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="test-key",
        key=_KEY,
        source_path="test-media",
    )
    assert created
    common = {
        "capture_id": capture_id,
        "content_sha256": content_sha256,
        "raw_ref": raw_ref_for(record),
        "kind": "audio",
        "lane": media_ingress.LANE_MEDIA_INGRESS,
        "trace_id": "t-seam",
        "event_payload": {"capture_id": capture_id, "content_sha256": content_sha256},
    }
    first, newly = media_ingress.record_media_admission(**common)
    assert newly
    second, newly_again = media_ingress.record_media_admission(**common)
    assert not newly_again
    assert second.receipt_id == first.receipt_id
    assert len(all_media_receipts()) == 1


@pytest.mark.pg
def test_append_only_enforced_pg_media_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real Postgres trigger rejects UPDATE/DELETE against heimdal_media_receipt (HEIM-1).

    Mirrors `test_raw_store.py::test_append_only_enforced_pg_read_receipt`: the
    Python store exposes no mutation, and the database refuses one anyway. Also
    exercises `_PgReceiptStore`'s insert/replay path, which the memory-backend
    tests above cannot reach.
    """
    pytest.importorskip("psycopg")
    del monkeypatch  # the root conftest's pg fixtures supply DSN + autocreate

    content_sha256 = hashlib.sha256(f"pg-media-receipt-{secrets.token_hex(8)}".encode()).hexdigest()
    receipt, created = media_receipts.append_media_receipt(
        capture_id=str(uuid4()),
        content_sha256=content_sha256,
        raw_ref="heimraw:pg-record",
        kind="audio",
        lane=media_ingress.LANE_MEDIA_INGRESS,
        trace_id="t-pg",
        payload={"device_id": "ipad-pg"},
    )
    assert created
    # The derived primary key makes a replay a no-op that returns the original
    # row rather than an UPDATE the trigger would reject.
    replayed, created_again = media_receipts.append_media_receipt(
        capture_id=receipt.capture_id,
        content_sha256=content_sha256,
        raw_ref="heimraw:pg-record",
        kind="audio",
        lane=media_ingress.LANE_MEDIA_INGRESS,
        trace_id="t-pg-2",
        payload={},
    )
    assert not created_again and replayed.receipt_id == receipt.receipt_id
    assert media_receipts.find_media_receipts_by_capture_ids([receipt.capture_id])[
        receipt.capture_id
    ].receipt_id == receipt.receipt_id

    conn = media_receipts._pg_connect()
    try:
        cur = conn.cursor()
        with pytest.raises(Exception) as excinfo:
            cur.execute(
                f"UPDATE {media_receipts._TABLE} SET kind = 'tampered' WHERE receipt_id = %s",
                (receipt.receipt_id,),
            )
        assert "append-only" in str(excinfo.value).lower() or "HEIM-1" in str(excinfo.value)

        with pytest.raises(Exception) as excinfo_del:
            cur.execute(
                f"DELETE FROM {media_receipts._TABLE} WHERE receipt_id = %s",
                (receipt.receipt_id,),
            )
        assert "append-only" in str(excinfo_del.value).lower() or "HEIM-1" in str(
            excinfo_del.value
        )
    finally:
        conn.close()


def test_startup_preflight_reports_ingress_unavailable_without_exiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#4422 enforcement: with the key absent, the api LIFESPAN startup runs the
    ingress preflight, the status surface reports both ingress lanes
    unavailable before any request, the process serves unrelated routes, and
    the request-time raw_store_key_unavailable contract is unchanged."""
    from app.heimdal import ingress_preflight

    monkeypatch.delenv("HEIMDAL_RAW_STORE_KEY", raising=False)
    ingress_preflight.reset_ingress_preflight()
    assert ingress_preflight.current_ingress_status() is None

    # TestClient's context manager runs the real lifespan — the production
    # startup path, not the helper in isolation.
    with TestClient(app) as started:
        recorded = ingress_preflight.current_ingress_status()
        assert recorded is not None
        assert recorded.raw_store_key_available is False
        assert recorded.lanes == {
            "media_ingress": "unavailable",
            "screen_capture": "unavailable",
        }

        # Surfaced on the status endpoint before any ingress request was made.
        status = started.get("/api/status")
        assert status.status_code == 200
        ingress = status.json()["heimdal_ingress"]
        assert ingress["raw_store_key_available"] is False
        assert ingress["lanes"]["media_ingress"] == "unavailable"
        assert ingress["lanes"]["screen_capture"] == "unavailable"

        # Unrelated routes keep serving: the process did not exit or degrade.
        assert started.get("/api/health").status_code in (200, 503)

        # The request-time named contract is unchanged.
        media = b"still refused bytes"
        refused = _post_media(started, media, _sidecar(media))
        assert refused.status_code == 500
        assert refused.json()["detail"]["error"] == "raw_store_key_unavailable"
        assert refused.json()["detail"]["state"] == "not_acknowledged"


def test_startup_preflight_reports_missing_raw_liveness_schema(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing liveness migration makes both raw ingress lanes unavailable."""
    from app.heimdal import ingress_preflight

    def _missing_schema() -> None:
        raise ingress_preflight.raw_liveness.RawLivenessSchemaMissingError(
            "missing migration-owned liveness tables"
        )

    monkeypatch.setattr(ingress_preflight.raw_liveness, "assert_runtime_schema", _missing_schema)
    ingress_preflight.reset_ingress_preflight()

    recorded = ingress_preflight.run_ingress_preflight()

    assert recorded.raw_store_key_available is True
    assert recorded.raw_liveness_schema_available is False
    assert recorded.lanes == {
        "media_ingress": "unavailable",
        "screen_capture": "unavailable",
    }
    assert ingress_preflight.DETAIL_RAW_LIVENESS_SCHEMA_UNAVAILABLE in recorded.detail


def test_startup_preflight_reports_missing_media_consent_grant(
    client: TestClient,
) -> None:
    """#4492 enforcement: the media lane's standing consent grant is a runtime
    precondition, so the api LIFESPAN preflight reports the lane unavailable
    with a named detail before any request — not only on the first upload.

    The raw-store key is present here, so the only failing precondition is the
    grant: the screen lane must stay `available`, proving the check is scoped
    to the media lane rather than degrading both.
    """
    from app.heimdal import ingress_preflight

    revoke_consent(grant_ref=MEDIA_CAPTURE_GRANT_REF, revoked_by="test-operator")
    ingress_preflight.reset_ingress_preflight()
    assert ingress_preflight.current_ingress_status() is None

    # TestClient's context manager runs the real lifespan — the production
    # startup path (`app/api/app.py :: lifespan`), not the helper in isolation.
    with TestClient(app) as started:
        recorded = ingress_preflight.current_ingress_status()
        assert recorded is not None, "the lifespan must have run the preflight"
        assert recorded.raw_store_key_available is True
        assert recorded.media_consent_grant_available is False
        assert recorded.lanes == {
            "media_ingress": "unavailable",
            "screen_capture": "available",
        }
        assert (
            ingress_preflight.DETAIL_MEDIA_CONSENT_GRANT_MISSING in recorded.detail
        )

        # Surfaced on the status endpoint before any ingress request was made.
        status = started.get("/api/status")
        assert status.status_code == 200
        ingress = status.json()["heimdal_ingress"]
        assert ingress["media_consent_grant_available"] is False
        assert ingress["lanes"]["media_ingress"] == "unavailable"
        assert ingress["lanes"]["screen_capture"] == "available"

        # Unrelated routes keep serving: degrade-visibly, never fail-exit.
        assert started.get("/api/health").status_code in (200, 503)

        # The request-time named contract is unchanged.
        media = b"still refused bytes"
        refused = _post_media(started, media, _sidecar(media))
        assert refused.status_code == 409
        assert refused.json()["detail"]["error"] == "consent_refused"
        assert refused.json()["detail"]["state"] == "not_acknowledged"
        assert all_raw_records() == []
        assert all_media_receipts() == []


def test_startup_preflight_reports_an_unreadable_consent_ledger(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#4492: a ledger that cannot be queried at all is its own named class.

    This is the branch where a false `available` hurts most — an unmigrated or
    unreachable database — and it must not be conflated with
    `media_consent_grant_missing`, because the operator remedies differ
    (`alembic upgrade head` for the missing *table* vs re-granting a revoked
    grant). Raised from the real ledger read the preflight performs.
    """
    from app.heimdal import ingress_preflight

    def _unreadable(**_kwargs: Any):
        raise ConsentLedgerSchemaMissingError("Missing table 'heimdal_consent_grant'.")

    monkeypatch.setattr(ingress_preflight, "resolve_active_grant", _unreadable)
    ingress_preflight.reset_ingress_preflight()

    recorded = ingress_preflight.run_ingress_preflight()
    assert recorded.media_consent_grant_available is False
    assert recorded.raw_store_key_available is True
    assert recorded.lanes["media_ingress"] == "unavailable"
    # The screen lane has no consent precondition of its own, so it stays up.
    assert recorded.lanes["screen_capture"] == "available"
    # Named class plus the concrete error type, and never the grant-missing
    # class, which would send the operator hunting for a revocation.
    assert recorded.detail.startswith(
        ingress_preflight.DETAIL_MEDIA_CONSENT_LEDGER_UNREADABLE + ":"
    )
    assert "ConsentLedgerSchemaMissingError" in recorded.detail
    assert ingress_preflight.DETAIL_MEDIA_CONSENT_GRANT_MISSING not in recorded.detail


def test_preflight_logs_the_remedy_matching_the_failing_precondition(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """#4492: the two detail classes have different operator remedies, so the
    log must not hand the operator the wrong one.

    The log line is what an operator actually reads when a lane goes dark; a
    single shared remedy would send someone hunting for a revocation that does
    not exist (or vice versa).
    """
    from app.heimdal import ingress_preflight

    # 1. Unreadable ledger -> point at the *table*-owning migration and the DSN.
    def _unreadable(**_kwargs: Any):
        raise ConsentLedgerSchemaMissingError("Missing table 'heimdal_consent_grant'.")

    monkeypatch.setattr(ingress_preflight, "resolve_active_grant", _unreadable)
    ingress_preflight.reset_ingress_preflight()
    with caplog.at_level(logging.ERROR, logger="app.heimdal.ingress_preflight"):
        ingress_preflight.run_ingress_preflight()
    unreadable_log = caplog.text
    assert "could not be read at all" in unreadable_log
    assert "c4f7a1b2d9e3" in unreadable_log, "must name the table-owning migration"
    assert "re-granted" not in unreadable_log, "wrong remedy for an unreadable ledger"

    # 2. Readable ledger, no active grant -> point at *this* slice's migration
    #    and at re-granting.
    monkeypatch.undo()
    caplog.clear()
    revoke_consent(grant_ref=MEDIA_CAPTURE_GRANT_REF, revoked_by="test-operator")
    ingress_preflight.reset_ingress_preflight()
    with caplog.at_level(logging.ERROR, logger="app.heimdal.ingress_preflight"):
        ingress_preflight.run_ingress_preflight()
    missing_log = caplog.text
    assert "no active grant covers the scope" in missing_log
    assert "a9f3c2d7b6e1" in missing_log, "must name the grant-seeding migration"
    assert "re-granted" in missing_log
    assert "could not be read at all" not in missing_log


def test_admission_succeeds_when_key_provisioned(client: TestClient) -> None:
    """#4422: with the key present, the preflight passes and admission returns
    a durable receipt through the production route."""
    from app.heimdal import ingress_preflight

    ingress_preflight.reset_ingress_preflight()
    with TestClient(app) as started:
        recorded = ingress_preflight.current_ingress_status()
        assert recorded is not None
        assert recorded.raw_store_key_available is True
        assert recorded.media_consent_grant_available is True
        assert recorded.detail == ""
        assert recorded.lanes == {
            "media_ingress": "available",
            "screen_capture": "available",
        }
        media = b"provisioned admission bytes"
        admitted = _post_media(started, media, _sidecar(media))
        assert admitted.status_code == 200, admitted.text
        body = admitted.json()
        assert body["outcome"] == "admitted"
        assert body["receipt_id"].startswith("rcp_")
