State: Accepted (doctrine-level architecture decision, 2026-06-26).
Doc role: Decision record (ADR)
Authority: Authoritative that derived representations are not primary evidence by default.
Owner: SIP / RCA / DRI / OEF / GOV / HKA
Temporal class: Durable decision
Source of truth: This ADR plus `../architecture/semantic-dimensions.md` and `../architecture/metadata-bundle.md`
Parent issue: #2533
Related issue: #2549

# ADR-0033: Projection is not evidence

**Date:** 2026-06-26
**Status:** Accepted

## Context

Dashboards, summaries, context bundles, embeddings, graph overlays, and agent answers are derived
representations. Treating them as sources lets unverified derivations stand in for primary material
and quietly launder authority.

## Decision

> Projections, summaries, context bundles, embeddings, dashboards, and agent answers are derived
> representations, not primary evidence by default. `evidence_role` defaults to `non_evidence` for a
> projection.

## Consequences

- A projection can support navigation and explanation but cannot stand as a source.
- Retrieval and context artifacts must preserve provenance (matrix row 16); a projection candidate is
  not evidence by default.
- A projection becomes usable evidence only through provenance-backed promotion or citation
  ([ADR-0031](./ADR-0031-authority-transition-flow-governs-durable-mutation.md)).

## Affected boundaries

SIP, RCA, DRI, OEF, HKA, GOV, HIX.

## Affected invariants

- Traceability matrix row 8 (projection is not evidence), row 16 (derived/rebuildable representations
  must preserve metadata and provenance).
- Doctrine §2.5 (projections are not evidence).

## Related docs

- Anchored in the [doctrine](../foundation/00-yggdrasil-doctrine.md) and [traceability matrix](../architecture/traceability-matrix.md).
- [Semantic dimensions](../architecture/semantic-dimensions.md) ·
  [metadata-bundle](../architecture/metadata-bundle.md) ·
  [retrieval-contract](../architecture/retrieval-contract.md) ·
  [context-envelope](../architecture/context-envelope.md)
- Related decisions: [ADR-0018](./ADR-0018-provenance-split.md) (provenance split),
  [ADR-0022](./ADR-0022-oef-first-class-non-authoritative.md) (OEF non-authoritative),
  [ADR-0024](./ADR-0024-retrieval-topology.md) (retrieval is a serving projection).

## Related contracts / schemas

- [`metadata-bundle.schema.json`](../../schemas/metadata-bundle.schema.json) ·
  [`retrieval-result.schema.json`](../../schemas/retrieval-result.schema.json) ·
  [`context-envelope.schema.json`](../../schemas/context-envelope.schema.json).

## Related tests / future fitness checks

- Anti-contamination eval corpus — #2551; invariant registry — #2550.
