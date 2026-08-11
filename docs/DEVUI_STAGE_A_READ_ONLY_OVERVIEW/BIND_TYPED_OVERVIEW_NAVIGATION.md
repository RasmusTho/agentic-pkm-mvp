---
name: Bind Typed Overview Navigation
description: Bind Overview typed references only to real admitted local Focus and optional SoI destinations without joining their payloads.
task_id: ARO-04
github_issue: 4745
source_anchor: "docs/DEVUI.md :: DEVUI-OVERVIEW-BOUNDARY — server-declared read model"
parent_capability: devUI Stage A Read-Only Overview
prerequisites: [ARO-03, Focus route #4768]
depends_on: [EXPOSE_LOCAL_OVERVIEW_GET_ROUTE.md]
can_parallelize_with: []
recommended_capability: "Codex Terra / high"
capability_rationale: "Typed route binding must preserve identity and root authority while failing closed on absent destinations."
execution_context: fresh_issue_agent
issue_local_helper_budget: 0
context_cost_estimate: medium
complexity: medium
verification_difficulty: high
defect_blast_radius: medium
review_gate: independent route-identity review plus exact-head CI
---

# Bind Typed Overview Navigation

## Purpose

Turn typed root identities into honest local navigation only when real destinations exist.

## Context

Parent: #4741

Make Overview-to-Focus and optional SoI references resolvable only after the corresponding local
destination contracts and GET routes exist. Until then, retain explicit unavailable/unsupported
references instead of dead links.

## Scope

- Bind available Focus references only to an actual admitted local GET destination.
- Bind the optional SoI reference only when its local destination exists.
- Preserve subject/evidence identity and typed-root separation; retain honest unavailable states.

## What This Task Does

- Maps typed references to admitted local GET targets without importing destination payloads.
- Leaves unavailable or unsupported references non-navigable.

## Concretely

A Focus reference becomes available only after its stable subject resolves at a local Focus GET;
an absent SoI route remains an explicitly unsupported reference, not `/soi/<guessed-id>`.

## Why This Matters

Typed data without a real route can create dead links or silently couple Overview to standalone UIs.

## Source Anchors

- `docs/DEVUI.md :: DEVUI-OVERVIEW-BOUNDARY — server-declared read model`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Dependency order and readiness`
- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md :: Information architecture and hard boundary`

## SBS Impact

- Primary subsystem: Builder System / devUI route binding
- Secondary subsystem(s): Focus route; Product/Runtime SoI reference boundary
- Write class: GET-only typed navigation adapter
- Authority impact: none; navigation never inherits destination authority
- Persistence impact: none
- Derived/rebuildable impact: per-read resolvable root references
- Human knowledge impact: none
- Memory impact: none
- Retrieval/context impact: stable subject/evidence reference transport only
- Sync/deployment impact: local API route only
- External boundary impact: typed reference to Product/Runtime SoI, never a join
- New or changed contract: resolvable local destination binding
- Owner-doc impact: none until capability acceptance
- Transition debt impact: prevents dead/synthetic links and standalone-UI coupling
- Fitness rule impact: real-target, identity, local-GET, no-join tests

## Constraints

The binding adapter and API proof are limited to `app/api/routes/devui.py` and
`tests/api/test_devui_api.py`. Browser link rendering remains ARO-06. Destination implementation is
not authorized by this child.

## Acceptance Criteria

- [ ] Every available Focus reference resolves to an admitted local GET destination carrying the
      identical stable subject and evidence references.
  - Verify: `tests/api/test_devui_api.py :: test_overview_focus_reference_resolves_without_identity_drift`
- [ ] Optional SoI references resolve only to an actual local SoI evidence destination; absence is
      unsupported/unavailable rather than a fabricated path.
  - Verify: `tests/api/test_devui_api.py :: test_overview_soi_reference_fails_closed_without_destination`
- [ ] Focus, SoI, delivery, and Builder System Control references remain typed separate roots and
      never import or join destination payloads into Overview.
  - Verify: `tests/api/test_devui_api.py :: test_overview_navigation_never_joins_root_payloads`
- [ ] No available link can return 404, cross the local admission boundary, or invoke a write method.
  - Verify: `tests/api/test_devui_api.py :: test_overview_available_navigation_targets_are_local_gets`

## How to Verify (Pre-Merge)

- Run the four named API tests against real destination routes, not mocks of nonexistent paths.
- Run `git diff --check`; prove exact-file scope.

## Suggested Validation

- Execute every named route-identity test against real local destinations.

## Out of Scope

- Implementing Focus/SoI semantics or routes, changing the composer, visual rendering, deep links
  to standalone subsystem UIs, or any payload join.

## Related Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md`
- `docs/DEVUI.md`

## Source Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DEVUI.md`
- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md`

## Applies learning (optional)

- None.

## Related GitHub Issues

Filed as blocked child [#4745](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4745); the exact
next trigger is #4744 delivery plus the merged admitted local
[Focus route #4768](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4768) (and a local SoI
route before any SoI reference is marked available).
