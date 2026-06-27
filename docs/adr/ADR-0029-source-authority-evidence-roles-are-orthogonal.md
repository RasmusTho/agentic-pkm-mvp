State: Accepted (doctrine-level architecture decision, 2026-06-26).
Doc role: Decision record (ADR)
Authority: Authoritative that the three role dimensions are separate and non-collapsible.
Owner: SIP / GOV / HKA / MEM
Temporal class: Durable decision
Source of truth: This ADR plus `../architecture/semantic-dimensions.md`
Parent issue: #2533
Related issue: #2549

# ADR-0029: source_role, authority_state, and evidence_role are orthogonal

**Date:** 2026-06-26
**Status:** Accepted

## Context

Origin, standing, and reasoning-permission are routinely conflated into a single "type" or "trust"
field. Collapsing them silently grants authority or evidence weight from mere origin, which is how
boundaries leak.

## Decision

> `source_role`, `authority_state`, and `evidence_role` are separate semantic dimensions and must
> never be collapsed into one field.

## Consequences

- Origin does not imply authority: a human `source_role` does not set `authority_state` to
  `accepted`/`canonical`
  ([ADR-0031](./ADR-0031-authority-transition-flow-governs-durable-mutation.md); matrix row 15).
- Authority does not imply admissibility as evidence: an accepted artifact still carries its own
  `evidence_role`.
- Evidence role does not grant retrieval, citation, or mutation permission — that is a
  `CrossScopeFlow` decision ([ADR-0028](./ADR-0028-cross-scope-flow-replaces-general-knowledge-boolean.md)).
- Schemas must encode the three as distinct fields/enums; `schemas/_defs.schema.json` pins the value
  families so they cannot collapse.

## Affected boundaries

SIP, GOV, HKA, RCA, MEM, DRI, OEF.

## Affected invariants

- Traceability matrix row 5 (the three role dimensions are orthogonal / non-collapsible).
- Doctrine §3 (distinctions that must not collapse).

## Related docs

- [Semantic dimensions](../architecture/semantic-dimensions.md) · [Doctrine](../foundation/00-yggdrasil-doctrine.md)
- [SIP charter](../boundaries/SIP.md) · [Traceability matrix](../architecture/traceability-matrix.md)
- Builds on [ADR-0018](./ADR-0018-provenance-split.md) (provenance ownership maps onto these dimensions).

## Related contracts / schemas

- [metadata-bundle](../architecture/metadata-bundle.md) /
  [`metadata-bundle.schema.json`](../../schemas/metadata-bundle.schema.json);
  shared value families in [`_defs.schema.json`](../../schemas/_defs.schema.json).

## Related tests / future fitness checks

- Invariant registry — #2550 (cross-field equality / non-collapse checks; monotonic evidence-role
  checks); anti-contamination eval corpus — #2551.
