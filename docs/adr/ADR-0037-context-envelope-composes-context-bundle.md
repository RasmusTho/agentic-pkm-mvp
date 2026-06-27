State: Accepted (doctrine-level architecture decision, 2026-06-26).
Doc role: Decision record (ADR)
Authority: Authoritative on the ContextEnvelope / ContextBundle relationship.
Owner: RCA / CAO / GOV
Temporal class: Durable decision
Source of truth: This ADR plus `../architecture/context-envelope.md` and `../architecture/retrieval-contract.md`
Parent issue: #2533
Related issue: #2549

# ADR-0037: ContextEnvelope composes ContextBundle

**Date:** 2026-06-26
**Status:** Accepted

## Context

`ContextEnvelope` and `ContextBundle` are easy to conflate now that both exist as contracts. Merging
them — or letting the envelope quietly replace the bundle — would erase the evidence-packaging
contract that retrieval depends on.

## Decision

> `ContextBundle` is the RCA evidence/context package. `ContextEnvelope` is the broader bounded
> operating-context contract consumed by CAO and agents. A `ContextEnvelope` may contain or reference
> `ContextBundle`s but does not replace them.

## Consequences

- The envelope references bundles by id (`context_bundles[].context_bundle_id`); it never redefines
  them.
- When the need is evidence packaging, extend `ContextBundle`. Define or extend `ContextEnvelope`
  only for the bounded operating context — active scope, allowed capabilities, denied scopes,
  policies, cross-scope flows, and escalation conditions.

## Affected boundaries

RCA, CAO, GOV, WSP.

## Affected invariants

- Traceability matrix rows 1/7/8 (retrieval/projection semantics are carried into, not erased by, the
  envelope).
- Doctrine §2.5 (projections are not evidence) — the envelope does not upgrade a bundle's standing.

## Related docs

- Anchored in the [doctrine](../foundation/00-yggdrasil-doctrine.md) and [traceability matrix](../architecture/traceability-matrix.md).
- [context-envelope](../architecture/context-envelope.md) ·
  [retrieval-contract](../architecture/retrieval-contract.md)
- Related decision: [ADR-0039](./ADR-0039-retrieval-result-is-candidate-context-not-authority.md).

## Related contracts / schemas

- [`context-envelope.schema.json`](../../schemas/context-envelope.schema.json) ·
  [`retrieval-result.schema.json`](../../schemas/retrieval-result.schema.json).

## Related tests / future fitness checks

- Invariant registry — #2550.
