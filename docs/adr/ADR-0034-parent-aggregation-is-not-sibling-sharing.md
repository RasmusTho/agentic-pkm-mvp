State: Accepted (doctrine-level architecture decision, 2026-06-26).
Doc role: Decision record (ADR)
Authority: Authoritative that aggregation does not create sibling/ambient access, and that sync/federation preserve boundaries.
Owner: SFC / WSP / GOV
Temporal class: Durable decision
Source of truth: This ADR plus `../architecture/cross-scope-flow.md` and the SFC charter
Parent issue: #2533
Related issue: #2549

# ADR-0034: Parent aggregation is not sibling sharing

**Date:** 2026-06-26
**Status:** Accepted

## Context

A parent or master aggregate that pools child scopes must not become an implicit cross-scope channel
between children, and replication across nodes must not dissolve scope boundaries. Both are easy
places for "it's all under one parent" to silently grant access.

## Decision

> Parent/master aggregation does not imply sibling sharing or child-to-parent ambient access.
> Synchronization and federation preserve scope boundaries.

## Consequences

- SFC preserves replicated topology and boundaries across nodes, replicas, and devices (sync
  preserves boundaries — matrix row 14).
- GOV controls cross-scope flow; WSP binds the current context but cannot grant access.
- Parent aggregate views require explicit configuration or a typed `CrossScopeFlow`
  ([ADR-0028](./ADR-0028-cross-scope-flow-replaces-general-knowledge-boolean.md)), not ambient
  inheritance.

## Affected boundaries

SFC, WSP, GOV, RCA, SIP, OEF.

## Affected invariants

- Traceability matrix row 11 (parent aggregation is not sibling sharing), row 14 (sync preserves
  boundaries).
- Doctrine §2.1–§2.2.

## Related docs

- Anchored in the [doctrine](../foundation/00-yggdrasil-doctrine.md) and [traceability matrix](../architecture/traceability-matrix.md).
- [CrossScopeFlow](../architecture/cross-scope-flow.md) ·
  [context-envelope](../architecture/context-envelope.md) ·
  [SFC charter](../boundaries/SFC.md) · [WSP charter](../boundaries/WSP.md) ·
  [GOV charter](../boundaries/GOV.md)
- Related decision: [ADR-0020](./ADR-0020-sfc-single-node-upgrade-path.md) (SFC single-node posture).

## Related contracts / schemas

- [`retrieval-result.schema.json`](../../schemas/retrieval-result.schema.json) ·
  [`context-envelope.schema.json`](../../schemas/context-envelope.schema.json) ·
  [`metadata-bundle.schema.json`](../../schemas/metadata-bundle.schema.json) ·
  [REPLICATION_ENVELOPE.md](../contracts/REPLICATION_ENVELOPE.md).

## Related tests / future fitness checks

- Anti-contamination eval corpus — #2551 (denied-scope non-leak probes);
  `tests/sfc/test_replication_envelope.py` (existing); invariant registry — #2550.
