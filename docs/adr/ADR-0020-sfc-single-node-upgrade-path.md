State: Accepted (target-state architecture decision, 2026-06-21).
Doc role: Decision record (ADR)
Authority: Authoritative target decision for SFC naming and V1 posture.
Owner: SFC / Architecture spine
Temporal class: Durable decision
Source of truth: This ADR plus `docs/contracts/REPLICATION_ENVELOPE.md`

# ADR-0020: Declare SFC now with single-node/no-op posture until federation is scheduled

**Date:** 2026-06-21
**Status:** Accepted

## Context

Future multi-device, central/satellite, offline/online, and multi-write deployments need node identity, replica identity, causal ordering, conflict staging, and distributed receipt continuity. The current runtime should not pay distributed-systems cost prematurely.

## Decision

Synchronization, Federation & Consensus is a target subsystem now. V1 may be a no-op single-node implementation.

The architecture still defines a ReplicationEnvelope contract and preserves an upgrade path for multi-device, central/satellite, and multi-write deployments.

## Consequences

- Distribution complexity is named early without premature consensus implementation.
- Sync is not treated as persistence or integration.
- Semantic conflict resolution remains under GOV/HIX policy rather than SFC transport rules.

## Validation

Any sync/federation work must classify delivery semantics, idempotency, replay/backfill, conflict envelope, and single-node-to-federated transition posture.

## References

- `docs/contracts/REPLICATION_ENVELOPE.md`
- `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md`
- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/CONCEPTS/INSTANCE_DEVICE_AND_REPLICA_CONTRACT.md`
