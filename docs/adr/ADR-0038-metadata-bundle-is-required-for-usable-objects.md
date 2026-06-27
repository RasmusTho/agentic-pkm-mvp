State: Accepted follow-up — optional doctrine ADR beyond the ten required by #2549 (2026-06-26).
Doc role: Decision record (ADR)
Authority: Authoritative that every usable object carries or references its metadata bundle.
Owner: HKA / SIP / PDM / GOV
Temporal class: Durable decision
Source of truth: This ADR plus `../architecture/metadata-bundle.md`
Parent issue: #2533
Related issue: #2549

# ADR-0038: MetadataBundle is required for usable objects

**Date:** 2026-06-26
**Status:** Accepted (follow-up; optional addition beyond the #2549 required set ADR-0026–ADR-0035)

## Context

Without a required semantic envelope, an object loses its scope, role, authority, evidence,
sensitivity, suppression, and provenance meaning the moment it is stored, indexed, retrieved, or
projected — and the distinctions the doctrine protects silently disappear.

## Decision

> Every usable object must carry or reference the `MetadataBundle` needed for scope, role, authority,
> evidence, sensitivity, suppression, and provenance semantics.

## Consequences

- Storage, indexing, retrieval, and projection must preserve the bundle, not strip it (storage
  preserves but does not define meaning — matrix row 12; derived must preserve provenance — row 16).
- The bundle binds the orthogonal role dimensions
  ([ADR-0029](./ADR-0029-source-authority-evidence-roles-are-orthogonal.md)) to each object via
  `schemas/metadata-bundle.schema.json` and the shared `schemas/_defs.schema.json` value families.

## Affected boundaries

HKA, SIP, PDM, DRI, RCA, GOV, MEM.

## Affected invariants

- Traceability matrix row 12 (storage preserves but does not define meaning), row 16
  (derived/rebuildable representations must preserve metadata and provenance).
- Doctrine §3 (distinctions that must not collapse).

## Related docs

- Anchored in the [doctrine](../foundation/00-yggdrasil-doctrine.md) and [traceability matrix](../architecture/traceability-matrix.md).
- [metadata-bundle](../architecture/metadata-bundle.md)
- Related decisions: [ADR-0018](./ADR-0018-provenance-split.md),
  [ADR-0029](./ADR-0029-source-authority-evidence-roles-are-orthogonal.md).

## Related contracts / schemas

- [`metadata-bundle.schema.json`](../../schemas/metadata-bundle.schema.json) ·
  [`_defs.schema.json`](../../schemas/_defs.schema.json).

## Related tests / future fitness checks

- Invariant registry — #2550.
