State: Accepted (doctrine-level architecture decision, 2026-06-26).
Doc role: Decision record (ADR)
Authority: Authoritative doctrine-level decision that durable human knowledge changes only through governed AuthorityTransition.
Owner: GOV / HKA / SIP / MEM
Temporal class: Durable decision
Source of truth: This ADR plus `../architecture/authority-transition-flow.md` and [ADR-0019](./ADR-0019-governed-writes-decision-token-authority-receipt.md)
Parent issue: #2533
Related issue: #2549

# ADR-0031: AuthorityTransition governs durable mutation

**Date:** 2026-06-26
**Status:** Accepted

## Context

Agent proposals, memory promotion, repair, and sync conflict resolution must not directly mutate
accepted human knowledge. Without a single governed seam, any of these paths could silently change
what the human holds as durable.

## Decision

> Durable human knowledge changes only through a governed `AuthorityTransition` (WriteGuard-equivalent)
> flow that emits a receipt.

## Consequences

- Agent proposals are not mutations; persistence writes are not authority transitions.
- Sync conflict resolution that changes semantic authority requires governance.
- Authority-bearing transitions carry DecisionToken / AuthorityReceipt semantics (the *mechanism* is
  recorded in [ADR-0019](./ADR-0019-governed-writes-decision-token-authority-receipt.md)).
- DRI must invalidate or rebuild affected derived representations after accepted transitions; the
  `affected_derived_representation_ids` field makes the rebuild obligation explicit.

## Affected boundaries

GOV, HKA, SIP, PDM, DRI, MEM, CAO, EXE, SFC, OEF.

## Affected invariants

- Traceability matrix row 9 (authority transitions require governance and receipts), row 10
  (execution cannot authorize itself).
- Doctrine §2.6 (human authority changes durable knowledge only through governed transition).

## Related docs

- Anchored in the [doctrine](../foundation/00-yggdrasil-doctrine.md) and [traceability matrix](../architecture/traceability-matrix.md).
- [authority-transition-flow](../architecture/authority-transition-flow.md) ·
  [GOV charter](../boundaries/GOV.md) · [HKA charter](../boundaries/HKA.md)
- Related decisions: [ADR-0019](./ADR-0019-governed-writes-decision-token-authority-receipt.md)
  (token/receipt mechanism), [ADR-0017](./ADR-0017-human-knowledge-and-governance-survivability.md)
  (survivability), [ADR-0030](./ADR-0030-agent-memory-is-noncanonical.md) (memory promotion path).

## Related contracts / schemas

- [`authority-transition.schema.json`](../../schemas/authority-transition.schema.json) ·
  [GOVERNED_WRITE_PROTOCOL.md](../contracts/GOVERNED_WRITE_PROTOCOL.md) ·
  [`metadata-bundle.schema.json`](../../schemas/metadata-bundle.schema.json).

## Related tests / future fitness checks

- [SBS fitness rules](../architecture/SBS_FITNESS_RULES.md) (authority-bearing durable writes without
  DecisionToken and AuthorityReceipt are a blocking target invariant).
- Invariant registry — #2550; xfail invariant/eval skeletons — #2552.
