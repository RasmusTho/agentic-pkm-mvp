State: Accepted (doctrine-level architecture decision, 2026-06-26).
Doc role: Decision record (ADR)
Authority: Authoritative that cross-scope use is governed by typed grants, never a global boolean bypass.
Owner: GOV / WSP / RCA
Temporal class: Durable decision
Source of truth: This ADR plus `../architecture/cross-scope-flow.md`
Parent issue: #2533
Related issue: #2549

# ADR-0028: CrossScopeFlow replaces the general_knowledge boolean

**Date:** 2026-06-26
**Status:** Accepted

## Context

A global `general_knowledge: true` style flag would act as a universal bypass that waves material
across every scope, collapsing the four-part meaning of scope
([ADR-0027](./ADR-0027-scope-as-frame-audience-policy-and-provenance.md)). Similarity and eligibility
must never silently become permission.

## Decision

> Cross-scope use is governed by typed `CrossScopeFlow` grants. `general_knowledge: true` must not
> function as a universal bypass. `general_knowledge` may be a `source_role` or eligibility signal,
> but it does not itself authorize any crossing — each crossing remains an explicit typed flow.

## Consequences

- Each flow must specify source scope, target scope, allowed and denied operations, allowed source
  roles, allowed authority states, allowed evidence roles, redaction, confirmation, expiry, audit,
  and provenance requirements.
- The operations are distinct and separately granted:
  `retrieve` ≠ `surface` ≠ `cite` ≠ `import` ≠ `remember` ≠ `mutate` ≠ `execute` ≠ `export`.
- Similarity is not permission: embedding or keyword similarity may *suggest* relevance but never
  *grants* a crossing.
- Parent aggregation is not sibling sharing
  ([ADR-0034](./ADR-0034-parent-aggregation-is-not-sibling-sharing.md)).
- Re-introducing a global boolean bypass is an architecture violation.

## Affected boundaries

GOV, WSP, RCA, SIP, MEM, CAO, OEF.

## Affected invariants

- Traceability matrix row 6 (typed CrossScopeFlow replaces any global `general_knowledge` bypass),
  row 1 (similarity is not permission).
- Doctrine §2.1.

## Related docs

- [CrossScopeFlow](../architecture/cross-scope-flow.md) · [Doctrine](../foundation/00-yggdrasil-doctrine.md)
- [GOV charter](../boundaries/GOV.md) · [WSP charter](../boundaries/WSP.md) · [RCA charter](../boundaries/RCA.md)
- [Traceability matrix](../architecture/traceability-matrix.md)

## Related contracts / schemas

- [`retrieval-result.schema.json`](../../schemas/retrieval-result.schema.json) ·
  [`context-envelope.schema.json`](../../schemas/context-envelope.schema.json) ·
  [`metadata-bundle.schema.json`](../../schemas/metadata-bundle.schema.json).

## Related tests / future fitness checks

- Anti-contamination eval corpus — #2551 (RPG / private / work / general anti-contamination and
  denied-scope non-leak probes).
- Invariant registry — #2550; xfail invariant/eval skeletons — #2552.
