"""Synchronization, Federation & Consensus (SFC) subsystem package.

V1 posture is single-authoritative-node / no-op federation per ADR-0020. This
package names the distribution seam (the ReplicationEnvelope contract) without
implementing replication, consensus, or semantic conflict resolution.
"""
from __future__ import annotations

from app.sfc.replication_envelope import (
    DeliveryStatus,
    ReplicationEnvelope,
    SourceObservationEvent,
    build_source_observation_event,
    wrap_as_replication_envelope,
)

__all__ = [
    "DeliveryStatus",
    "ReplicationEnvelope",
    "SourceObservationEvent",
    "build_source_observation_event",
    "wrap_as_replication_envelope",
]
