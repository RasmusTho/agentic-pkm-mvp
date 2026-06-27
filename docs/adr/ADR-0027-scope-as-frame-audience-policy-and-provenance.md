State: Accepted (doctrine-level architecture decision, 2026-06-26).
Doc role: Decision record (ADR)
Authority: Authoritative on what "scope" means in Yggdrasil.
Owner: WSP / GOV / SIP
Temporal class: Durable decision
Source of truth: This ADR plus `../architecture/cross-scope-flow.md` and `../architecture/functional-ontology.md`
Parent issue: #2533
Related issue: #2549

# ADR-0027: Scope as frame, audience, policy, and provenance context

**Date:** 2026-06-26
**Status:** Accepted

## Context

"Scope" is routinely flattened to a vault, folder, device, or workspace. That flattening drops the
audience, policy, and provenance meaning a scope carries, and invites cross-scope leakage because the
container looks like the whole story.

## Decision

> Scope is simultaneously a cognitive frame, an audience boundary, a policy boundary, and a
> provenance context — all four at once. It is not merely a vault, folder, device, or workspace.

## Consequences

- WSP binds the current scope/principal context, but binding is **not** permission (context is not
  identity).
- GOV decides admissibility; SIP preserves provenance and semantic identity across the scope.
- Cross-scope use requires an explicit typed `CrossScopeFlow`
  ([ADR-0028](./ADR-0028-cross-scope-flow-replaces-general-knowledge-boolean.md)); proximity in one
  workspace never implies shared access.
- `scope_binding` is metadata, not an access grant.

## Affected boundaries

WSP, GOV, SIP, RCA, HIX, SFC.

## Affected invariants

- Traceability matrix row 2 (scope is frame, audience, policy, and provenance context).
- Doctrine §2.2. `scope_binding` ≠ permission.

## Related docs

- [CrossScopeFlow](../architecture/cross-scope-flow.md) · [Functional ontology](../architecture/functional-ontology.md)
- [Semantic dimensions](../architecture/semantic-dimensions.md) · [Doctrine](../foundation/00-yggdrasil-doctrine.md)
- [WSP charter](../boundaries/WSP.md) · [Traceability matrix](../architecture/traceability-matrix.md)

## Related contracts / schemas

- [metadata-bundle](../architecture/metadata-bundle.md) / [`metadata-bundle.schema.json`](../../schemas/metadata-bundle.schema.json)
  (`scope_id`, `sphere`, `scope_binding`).

## Related tests / future fitness checks

- Invariant registry — #2550; anti-contamination eval corpus — #2551.
