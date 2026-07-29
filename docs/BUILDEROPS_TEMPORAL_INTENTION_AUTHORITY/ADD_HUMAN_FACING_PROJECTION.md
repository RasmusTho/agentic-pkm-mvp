---
name: Add A Human-Facing Temporal-Intention Projection
description: Add a separately approved read-only human-facing view without giving it disposition or Product authority.
task_id: TIA-05
github_issue: 4380
source_anchor: docs/adr/ADR-0065-builderops-temporal-intention-authority.md :: D6 — Projections are rebuildable, read-only views
parent_capability: BuilderOps Temporal Intention Authority
prerequisites: [TIA-01, PRODUCT_HIX_PROJECTION_DECISION]
depends_on: [ADMIT_OPAQUE_LIFECYCLE_EVIDENCE.md]
can_parallelize_with: []
recommended_capability: "Codex Sol / high"
capability_rationale: "A human-facing BuilderOps/Product boundary needs explicit authority, privacy, and mutation design before UI work."
---

# Add A Human-Facing Temporal-Intention Projection

## Purpose

Create a bounded cockpit or other human-facing view only after an accepted Product/HIX decision
selects the surface, audience, fields, authority boundary, and any authenticated action path.

## What This Task Does

- Produces or cites the accepted surface-and-authority decision before implementation.
- Renders a labeled, read-only view from canonical records and append-only receipt lineage.
- Keeps lifecycle mutation behind the authenticated canonical API rather than the projection.
- Defines stale, missing, corrupt, duplicate, and rebuild behavior.

## Concretely

The initial projection may display only fields authorized by the decision. Static Markdown, HTML,
or cockpit state cannot itself carry `done`, `ignore`, `never_show_again`, expiry, or reversal
authority.

## Why This Matters

A useful view must not quietly become a second writer or blur BuilderOps operational evidence into
Product attention or intention semantics.

## Acceptance Criteria

- [ ] An accepted Product/HIX decision names the surface, audience, permitted fields, accessibility
  requirements, authority labels, and authenticated mutation boundary before the Issue becomes
  ready.
  - Verify: `runtime receipt: temporal_intention_tia05_contract_reconciliation.v1`
- [ ] The rendered view labels itself non-authoritative and can be deleted and rebuilt from
  canonical opaque identity plus receipt lineage.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_human_projection.py::test_human_view_is_labeled_read_only_and_rebuildable`
- [ ] Missing, stale, duplicate, or corrupt projection data cannot admit, reverse, expire, or
  otherwise change a disposition.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_human_projection.py::test_projection_failure_cannot_mutate_authority`
- [ ] Any permitted action crosses a separately authenticated API boundary and returns canonical
  receipt evidence; the renderer never writes state directly.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_human_projection.py::test_actions_use_authenticated_api_and_canonical_receipts`

## How to Verify (Pre-Merge)

- Reconcile this spec and live Issue to the accepted Product/HIX decision.
- Run the named rebuild, non-authority, authenticated-action, and accessibility tests.
- Run the external-boundary review-before-CI gate if the action path changes an API.

## Out of Scope

- Choosing a cockpit or Product surface before the decision.
- Direct projection writes, file authority, or client-local disposition state.
- New content fields not authorized by TIA-02.
- Product intention, commitment, attention, memory, or artifact semantics.

## Related Docs

- `docs/adr/ADR-0065-builderops-temporal-intention-authority.md`
- `docs/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY/README.md`
- `docs/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY/ADMIT_OPAQUE_LIFECYCLE_EVIDENCE.md`

## Related GitHub Issues

- Live task: [#4380](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4380).
