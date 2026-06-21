"""SFC ReplicationEnvelope adapter for watcher/sync events (#2362).

First containment seam for SBS transition-debt row D7 ("watcher/sync event
envelope lacking delivery semantics").

This adapter NAMES the distribution seam defined by
`docs/contracts/REPLICATION_ENVELOPE.md` and ADR-0020. It maps a single watcher
event path (`app.watcher.events.WatcherRunEvent`) into a
``SourceObservationEvent`` and wraps that into a ``ReplicationEnvelope`` carrying
explicit delivery semantics: node/replica identity placeholders, an idempotency
key derived from the event id, a replay/backfill cursor, delivery/ack status,
and a conflict-classification PLACEHOLDER.

Per ADR-0020 the V1 posture is single-authoritative-node / no-op federation:

- This module does NOT replicate, deliver to peers, or run consensus.
- The conflict placeholder does NOT resolve semantic meaning; per the contract's
  "Forbidden Use" it routes any classification to GOV/HIX rather than applying a
  transport-level rule such as last-write-wins.
- Delivery of a duplicate ``event_id`` is a stable no-op (idempotent), matching
  the single-node "already observed" posture.

It exists so future sync/federation work is designed against this contract
rather than as ad hoc watcher transport.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.watcher.events import WatcherRunEvent

# V1 single-authoritative-node placeholders. These are intentionally fixed
# sentinels, NOT runtime-discovered identity: ADR-0020 keeps V1 single-node, so
# there is exactly one authoritative node/replica until federation is scheduled.
LOCAL_NODE_ID = "node:local"
LOCAL_REPLICA_ID = "replica:authoritative"

# Conflict classification is deliberately NOT decided here. SFC transport must
# not assign semantic meaning to a conflict (see REPLICATION_ENVELOPE.md
# "Forbidden Use"); classification is staged for GOV/HIX authority resolution.
CONFLICT_UNCLASSIFIED = "unclassified"
CONFLICT_RESOLUTION_AUTHORITY = "GOV/HIX"


class DeliveryStatus(str, Enum):
    """Explicit, observable delivery/acknowledgement status.

    Single-node V1 only uses ``DELIVERED`` (local observation succeeded),
    ``DUPLICATE`` (idempotent no-op on a re-seen event), and ``FAILED``
    (delivery/observation failure that must stay visible to OEF). The remaining
    values name the federated states the contract must preserve without
    implementing them now.
    """

    PENDING = "pending"
    DELIVERED = "delivered"
    DUPLICATE = "duplicate"
    FAILED = "failed"


class ConflictClassification(BaseModel):
    """Conflict-classification PLACEHOLDER — staged, never resolved by SFC.

    SFC does not decide semantic conflict meaning. When a conflict is observed it
    is staged for ``resolution_authority`` (GOV/HIX) rather than resolved by a
    transport rule. V1 single-node never observes a real conflict, so the default
    is ``staged=False`` with an unclassified class.
    """

    staged: bool = False
    classification: str = CONFLICT_UNCLASSIFIED
    resolution_authority: str = CONFLICT_RESOLUTION_AUTHORITY
    detail: str | None = None


class SourceObservationEvent(BaseModel):
    """Normalized source-observation view of a watcher/sync event.

    Carries the source store/artifact/event reference plus instance provenance
    (which node/replica observed it) without redefining artifact identity.
    """

    event: str
    version: str
    timestamp: str
    trace_id: str
    event_id: str
    node_id: str = LOCAL_NODE_ID
    replica_id: str = LOCAL_REPLICA_ID
    source_component: str
    source_trigger: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ReplicationEnvelope(BaseModel):
    """ReplicationEnvelope per `docs/contracts/REPLICATION_ENVELOPE.md`.

    Names node/replica identity, an idempotency key, a replay/backfill cursor,
    delivery/ack status, and a staged conflict placeholder. V1 is
    single-authoritative-node / no-op: this object asserts delivery semantics; it
    does not replicate.
    """

    observation: SourceObservationEvent
    node_id: str
    replica_id: str
    idempotency_key: str
    replay_cursor: str
    delivery_status: DeliveryStatus = DeliveryStatus.PENDING
    conflict: ConflictClassification = Field(default_factory=ConflictClassification)
    single_authoritative_node: bool = True
    failure_reason: str | None = None

    @property
    def delivered(self) -> bool:
        """True when the envelope reached a terminal successful/no-op state."""
        return self.delivery_status in (DeliveryStatus.DELIVERED, DeliveryStatus.DUPLICATE)

    @property
    def failed(self) -> bool:
        """True when delivery failed; failure must stay visible to OEF."""
        return self.delivery_status is DeliveryStatus.FAILED


def _idempotency_key(event_id: str) -> str:
    """Derive a stable idempotency key from the event id.

    Same event id -> same key (idempotent). Derivation is deterministic and
    transport-local, not a semantic decision.
    """
    return f"watcher.run:{event_id}"


def _replay_cursor(event: WatcherRunEvent) -> str:
    """Replay/backfill cursor for this observation.

    The cursor is the monotonic-ish ordering reference a future replay/backfill
    would resume from. For the watcher path it is the run timestamp plus the
    event id, which is stable and replay-addressable on a single node.
    """
    return f"{event.timestamp}#{event.event_id}"


def build_source_observation_event(event: WatcherRunEvent) -> SourceObservationEvent:
    """Map a ``WatcherRunEvent`` into a normalized ``SourceObservationEvent``."""
    return SourceObservationEvent(
        event=event.event,
        version=event.version,
        timestamp=event.timestamp,
        trace_id=event.trace_id,
        event_id=event.event_id,
        source_component=event.source.component,
        source_trigger=event.source.trigger,
        payload=event.payload.model_dump(mode="json"),
    )


def wrap_as_replication_envelope(
    event: WatcherRunEvent,
    *,
    seen_event_ids: set[str] | None = None,
    failure_reason: str | None = None,
) -> ReplicationEnvelope:
    """Wrap a watcher event in a ``ReplicationEnvelope`` with delivery semantics.

    V1 single-node / no-op posture (ADR-0020):

    - ``idempotency_key`` is stable for a given ``event_id``.
    - When ``seen_event_ids`` already contains this event id, delivery is a
      ``DUPLICATE`` no-op (idempotent re-observation), and the event id is NOT
      re-added.
    - When ``failure_reason`` is provided, ``delivery_status`` is ``FAILED`` and
      the reason is recorded so OEF/logging/status can observe it; the event id
      is still recorded as observed.
    - Otherwise delivery is ``DELIVERED`` and the event id is recorded.

    ``seen_event_ids`` is the caller-owned idempotency ledger (single-node, in
    memory here). No replication, peer delivery, or consensus is performed.
    """
    observation = build_source_observation_event(event)
    idempotency_key = _idempotency_key(event.event_id)

    if seen_event_ids is not None and event.event_id in seen_event_ids:
        delivery_status = DeliveryStatus.DUPLICATE
        recorded_failure: str | None = None
    elif failure_reason is not None:
        delivery_status = DeliveryStatus.FAILED
        recorded_failure = failure_reason
        if seen_event_ids is not None:
            seen_event_ids.add(event.event_id)
    else:
        delivery_status = DeliveryStatus.DELIVERED
        recorded_failure = None
        if seen_event_ids is not None:
            seen_event_ids.add(event.event_id)

    return ReplicationEnvelope(
        observation=observation,
        node_id=LOCAL_NODE_ID,
        replica_id=LOCAL_REPLICA_ID,
        idempotency_key=idempotency_key,
        replay_cursor=_replay_cursor(event),
        delivery_status=delivery_status,
        failure_reason=recorded_failure,
    )


__all__ = [
    "CONFLICT_RESOLUTION_AUTHORITY",
    "CONFLICT_UNCLASSIFIED",
    "LOCAL_NODE_ID",
    "LOCAL_REPLICA_ID",
    "ConflictClassification",
    "DeliveryStatus",
    "ReplicationEnvelope",
    "SourceObservationEvent",
    "build_source_observation_event",
    "wrap_as_replication_envelope",
]
