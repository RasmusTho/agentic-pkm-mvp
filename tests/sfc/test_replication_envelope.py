"""Tests for the SFC ReplicationEnvelope watcher adapter (#2362).

Asserts the first containment seam for SBS transition-debt D7: explicit delivery
semantics (stable idempotency key, idempotent duplicate no-op), conflict staged
but NOT resolved by SFC, and observable failure/delivery status. The V1 posture
is single-authoritative-node / no-op per ADR-0020 — these tests assert delivery
semantics, not replication.
"""
from __future__ import annotations

from pathlib import Path

from app.sfc.replication_envelope import (
    CONFLICT_RESOLUTION_AUTHORITY,
    CONFLICT_UNCLASSIFIED,
    LOCAL_NODE_ID,
    LOCAL_REPLICA_ID,
    ConflictClassification,
    DeliveryStatus,
    ReplicationEnvelope,
    build_source_observation_event,
    wrap_as_replication_envelope,
)
from app.watcher.events import build_watcher_run_event


def _make_event(event_id: str | None = None):
    summary = {
        "changed": 1,
        "ingest_attempted": 1,
        "ingested": 1,
        "errors": 0,
        "dry_run": False,
        "limit_exceeded": False,
    }
    event = build_watcher_run_event(
        summary,
        vault_root=Path("/tmp/vault"),
        snapshot_path="/tmp/snap.json",
        trigger="registry:test_watcher",
    )
    if event_id is not None:
        event = event.model_copy(update={"event_id": event_id})
    return event


def test_wrap_carries_node_replica_identity_and_observation():
    event = _make_event(event_id="evt-1")

    envelope = wrap_as_replication_envelope(event)

    assert isinstance(envelope, ReplicationEnvelope)
    assert envelope.node_id == LOCAL_NODE_ID
    assert envelope.replica_id == LOCAL_REPLICA_ID
    assert envelope.single_authoritative_node is True
    assert envelope.observation.event == "watcher.run"
    assert envelope.observation.event_id == "evt-1"
    assert envelope.observation.source_trigger == "registry:test_watcher"
    # Replay/backfill cursor is present and replay-addressable.
    assert envelope.replay_cursor
    assert "evt-1" in envelope.replay_cursor


def test_idempotency_key_is_stable_for_same_event_id():
    event_a = _make_event(event_id="same-id")
    event_b = _make_event(event_id="same-id")
    event_c = _make_event(event_id="other-id")

    key_a = wrap_as_replication_envelope(event_a).idempotency_key
    key_b = wrap_as_replication_envelope(event_b).idempotency_key
    key_c = wrap_as_replication_envelope(event_c).idempotency_key

    assert key_a == key_b
    assert key_a != key_c


def test_duplicate_event_id_is_idempotent_no_op():
    seen: set[str] = set()
    event = _make_event(event_id="dup-1")

    first = wrap_as_replication_envelope(event, seen_event_ids=seen)
    second = wrap_as_replication_envelope(event, seen_event_ids=seen)

    assert first.delivery_status is DeliveryStatus.DELIVERED
    assert first.delivered is True
    # Re-delivery of the same event id is a no-op duplicate, not a second deliver.
    assert second.delivery_status is DeliveryStatus.DUPLICATE
    assert second.delivered is True
    # Ledger recorded the event id exactly once.
    assert seen == {"dup-1"}
    # Same idempotency key both times.
    assert first.idempotency_key == second.idempotency_key


def test_conflict_path_is_staged_not_resolved():
    envelope = wrap_as_replication_envelope(_make_event(event_id="evt-c"))

    # Default conflict placeholder: SFC does not decide meaning.
    assert envelope.conflict.staged is False
    assert envelope.conflict.classification == CONFLICT_UNCLASSIFIED
    assert envelope.conflict.resolution_authority == CONFLICT_RESOLUTION_AUTHORITY

    # When a conflict IS observed, it is staged for GOV/HIX, never resolved here.
    staged = ConflictClassification(
        staged=True,
        detail="two replicas reported divergent run state",
    )
    assert staged.staged is True
    # Even a staged conflict carries no SFC-decided meaning (unclassified) and
    # routes to the GOV/HIX authority rather than a transport rule.
    assert staged.classification == CONFLICT_UNCLASSIFIED
    assert staged.resolution_authority == CONFLICT_RESOLUTION_AUTHORITY


def test_failure_status_is_observable():
    seen: set[str] = set()
    event = _make_event(event_id="evt-fail")

    envelope = wrap_as_replication_envelope(
        event,
        seen_event_ids=seen,
        failure_reason="telemetry sink unreachable",
    )

    assert envelope.delivery_status is DeliveryStatus.FAILED
    assert envelope.failed is True
    assert envelope.delivered is False
    assert envelope.failure_reason == "telemetry sink unreachable"
    # Failure visibility: the event id is still recorded so OEF/status can see it.
    assert seen == {"evt-fail"}
    # Failure is serializable for logging/status surfaces.
    dumped = envelope.model_dump(mode="json")
    assert dumped["delivery_status"] == "failed"
    assert dumped["failure_reason"] == "telemetry sink unreachable"


def test_source_observation_event_normalizes_watcher_event():
    event = _make_event(event_id="evt-obs")

    observation = build_source_observation_event(event)

    assert observation.event == "watcher.run"
    assert observation.version == event.version
    assert observation.trace_id == event.trace_id
    assert observation.event_id == "evt-obs"
    assert observation.node_id == LOCAL_NODE_ID
    assert observation.source_component == "watcher"
    # Payload is carried as a plain mapping (the source artifact/event reference).
    assert observation.payload["changed"] == 1
    assert observation.payload["ingested"] == 1
