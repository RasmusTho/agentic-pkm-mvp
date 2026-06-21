State: Target-state contract stub; V1 posture is single-authoritative-node/no-op federation.
Doc role: Contract stub
Authority: Owns the target SFC envelope for synchronization, federation, causal metadata, and conflict staging.
Owner subsystem: SFC - Synchronization, Federation & Consensus
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-21

# ReplicationEnvelope

## Purpose

Name the distribution seam before multi-device, central/satellite, or multi-write deployments are implemented.

## Inputs

- Node identity.
- Replica identity.
- Source store/artifact/event reference.
- Delivery semantics.
- Causal metadata placeholder.
- Conflict classification input.

## Outputs

- ReplicationEnvelope.
- Idempotency key.
- Replay/backfill cursor.
- Conflict envelope.
- Delivery/acknowledgement status.

## Commands

- Wrap delta.
- Replicate.
- Replay or backfill.
- Classify conflict.
- Stage conflict for GOV/HIX resolution.
- Record convergence status.

## Queries

- Which node/replica produced this envelope?
- Has this envelope been delivered or replayed?
- What causal metadata is known?
- Which conflicts require authority resolution?

## Events

- `replication.envelope_created`
- `replication.delivered`
- `replication.replayed`
- `replication.conflict_staged`
- `replication.converged`

## Invariants

- V1 is single-authoritative-node unless explicitly superseded.
- SFC does not decide semantic conflict meaning.
- Delivery, idempotency, replay/backfill, and failure visibility are explicit.
- Future central/satellite and multi-device posture must preserve distributed receipt continuity.

## Allowed Producers

- SFC replication/sync runtime.
- EBF transport adapters under SFC contract.
- PDM store change feeds when scoped by SFC.

## Allowed Consumers

- WSP topology, GOV conflict policy, HKA/SIP identity references, PDM store adapters, OEF audit.

## Forbidden Use

- Do not implement central/satellite as just another integration adapter.
- Do not apply last-write-wins to authority-bearing records without GOV policy.
- Do not hide delivery failure from OEF/HIX.

## Failure Modes

- Sync resolves meaning.
- Event envelope lacks delivery semantics.
- Distributed receipts become discontinuous.

## Transitional Implementation Notes

Current runtime should be read as single-node/single-authoritative posture. This contract exists to prevent future sync work from being designed as ad hoc watcher transport.

First seam: `app.sfc.replication_envelope` (#2362) wraps the `watcher.run` event path (`app.watcher.events.WatcherRunEvent`) into a `SourceObservationEvent` and a `ReplicationEnvelope`, naming the idempotency key, replay/backfill cursor, delivery/ack status, and a staged conflict placeholder. Per ADR-0020 it is single-node / no-op: it asserts delivery semantics and does not replicate. Conflict classification is staged for GOV/HIX, never resolved by SFC transport. Broader watcher/sync paths remain unwrapped (see SBS transition-debt D7).

## Open Questions

- What ReplicationEnvelope semantics are required before central/satellite deployment can be safe?
- Which conflict classes need human review by default?

## Linked Source-Of-Truth Docs

- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/CONCEPTS/INSTANCE_DEVICE_AND_REPLICA_CONTRACT.md`
- `docs/plans/PROTOCOL_SATELLITE_SYNC.md`
- `docs/plans/AUTONOMY_AND_SYNC_VALIDATION.md`
