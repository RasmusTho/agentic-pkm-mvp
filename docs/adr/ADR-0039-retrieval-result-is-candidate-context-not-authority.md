State: Accepted follow-up — optional doctrine ADR beyond the ten required by #2549 (2026-06-26).
Doc role: Decision record (ADR)
Authority: Authoritative that retrieval output is candidate context, not truth or authority.
Owner: RCA / GOV / SIP
Temporal class: Durable decision
Source of truth: This ADR plus `../architecture/retrieval-contract.md` and [ADR-0024](./ADR-0024-retrieval-topology.md)
Parent issue: #2533
Related issue: #2549

# ADR-0039: RetrievalResult is candidate context, not authority

**Date:** 2026-06-26
**Status:** Accepted (follow-up; optional addition beyond the #2549 required set ADR-0026–ADR-0035)

## Context

Retrieval ranks and packages relevant material. Treating its output as truth would let similarity
stand in for authority and bypass the admissibility decision that governance owns.

## Decision

> `RetrievalResult` represents candidate / admitted / redacted / escalated retrieval outputs and must
> not be treated as truth or authority by itself.

## Consequences

- Candidates carry their real `source_role` and `evidence_role`; a projection candidate is not
  evidence by default ([ADR-0033](./ADR-0033-projection-is-not-evidence.md)).
- Retrieval finds and packages; it does not create truth, authority, or cross-scope permission
  ([ADR-0028](./ADR-0028-cross-scope-flow-replaces-general-knowledge-boolean.md)).
- Escalated candidates are recorded content-free; redacted candidates are surfaceable only as
  redacted.

The retrieval *topology* (in-memory hybrid serving, weighted linear fusion, durable-spine direction)
is recorded in [ADR-0024](./ADR-0024-retrieval-topology.md); this ADR records the authority semantics
of the result contract.

## Affected boundaries

RCA, GOV, SIP, OEF.

## Affected invariants

- Traceability matrix row 7 (retrieval produces candidate evidence, not truth), row 1 (similarity is
  not permission).
- Doctrine §2.5 / §3 (retrieval result is candidate, not truth/authority).

## Related docs

- Anchored in the [doctrine](../foundation/00-yggdrasil-doctrine.md) and [traceability matrix](../architecture/traceability-matrix.md).
- [retrieval-contract](../architecture/retrieval-contract.md) ·
  [context-envelope](../architecture/context-envelope.md) · [RCA charter](../boundaries/RCA.md)
- Related decisions: [ADR-0024](./ADR-0024-retrieval-topology.md),
  [ADR-0028](./ADR-0028-cross-scope-flow-replaces-general-knowledge-boolean.md),
  [ADR-0033](./ADR-0033-projection-is-not-evidence.md),
  [ADR-0037](./ADR-0037-context-envelope-composes-context-bundle.md).

## Related contracts / schemas

- [`retrieval-result.schema.json`](../../schemas/retrieval-result.schema.json) ·
  [`context-envelope.schema.json`](../../schemas/context-envelope.schema.json).

## Related tests / future fitness checks

- Anti-contamination eval corpus — #2551; invariant registry — #2550.
