---
name: Expose the Local Overview GET Route
description: Expose the delivered composer over one local-only direct-loopback GET endpoint with no Overview candidates.
task_id: ARO-03
github_issue: 4744
source_anchor: "docs/plans/DEVUI_IMPLEMENTATION.md :: Stage A — see: coherent read-only devUI"
parent_capability: devUI Stage A Read-Only Overview
prerequisites: [ARO-01]
depends_on: []
can_parallelize_with: []
recommended_capability: "Codex Terra / high"
capability_rationale: "Small API slice with strict local admission, method, and semantic-envelope invariants."
execution_context: fresh_issue_agent
issue_local_helper_budget: 0
context_cost_estimate: medium
complexity: low
verification_difficulty: medium
defect_blast_radius: medium
review_gate: exact-head API review and CI
---

# Expose the Local Overview GET Route

## Purpose

Expose the delivered no-candidate Overview as one bounded local GET endpoint.

## Context

Parent: #4741

Serve the production `devui-overview-view.v1` result at `/api/devui/overview` without adding a
write path, cache, browser classification, or alternate composer.

## Scope

- Add `/api/devui/overview` as a per-request direct loopback over live composition and the delivered composer with no candidates.
- Reuse existing local admission and preserve the composer's explicit withdrawal state.
- Add no static assets, navigation destination, command, or write method.

## What This Task Does

- Reuses local admission, live composition, and the delivered composer without candidates.
- Returns the exact semantic envelope per request and rejects every mutation method.

## Concretely

`GET /api/devui/overview` returns `devui-overview-view.v1` from live composition and the delivered
composer with no candidates; a forwarded or non-local request is rejected and `POST /api/devui/overview`
is unavailable.

## Why This Matters

A separate route proof prevents the browser shell from becoming an implicit source reader or policy layer.

## Source Anchors

- `docs/plans/DEVUI_IMPLEMENTATION.md :: Stage A — see: coherent read-only devUI`
- `docs/DEVUI.md :: DEVUI-OVERVIEW-BOUNDARY — server-declared read model`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Dependency order and readiness`

## SBS Impact

- Primary subsystem: Builder System / devUI local API
- Secondary subsystem(s): BuilderOps producer/composer
- Write class: GET-only read adapter
- Authority impact: none
- Persistence impact: none
- Derived/rebuildable impact: one per-request Overview projection
- Human knowledge impact: none
- Memory impact: none
- Retrieval/context impact: none beyond existing source reads
- Sync/deployment impact: local API route only
- External boundary impact: single-operator local admission
- New or changed contract: local GET `/api/devui/overview`
- Owner-doc impact: none until capability acceptance
- Transition debt impact: exposes the canonical read model without duplicate logic
- Fitness rule impact: local-admission, method, envelope, statelessness tests

## Constraints

The delivered route reuses the existing local-admission dependency, builds live composition, and
calls the delivered composer with no candidates. It does not call a producer-enrichment path.

## Acceptance Criteria

- [ ] Local direct requests return exact `devui-overview-view.v1`; any forwarded, non-local, or
      ambiguous identity is rejected.
  - Verify: `tests/api/test_devui_api.py :: test_overview_route_reuses_local_admission_and_exact_contract`
- [ ] The no-candidate direct loopback preserves explicit source withdrawals instead of inferring
      owner authority or readiness.
  - Verify: `tests/api/test_devui_api.py :: test_overview_route_preserves_no_source_withdrawals`
- [ ] POST, PUT, PATCH, and DELETE are unavailable and the route has no command or mutation dependency.
  - Verify: `tests/api/test_devui_api.py :: test_overview_route_is_get_only`
- [ ] The route uses live composition and the delivered composer in the same request, without a
      candidate producer or reimplementation of zone rules.
  - Verify: `tests/api/test_devui_api.py :: test_overview_route_uses_live_composition_and_delivered_composer`

## How to Verify (Pre-Merge)

- Run the four named route tests and full `tests/api/test_devui_api.py`.
- Run `git diff --check` and prove exact-file scope.

## Suggested Validation

- Execute the complete devUI API module at the exact PR head.

## Out of Scope

- Producer semantics, composer changes, UI/static assets, navigation destinations, or any action endpoint.

## Related Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DEVUI.md`
- `app/api/routes/devui.py`

## Source Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DEVUI.md`
- `docs/plans/DEVUI_IMPLEMENTATION.md`

## Applies learning (optional)

- None.

## Related GitHub Issues

Delivered by [#4744](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4744) / PR #4772 as the
direct-loopback, no-candidate route after the accepted ARO-01 withdrawal decision.

## Delivery status

The delivered route is PR #4772 at head
`7b1f83d4a0b6bdd75071959c41146c70012a29d2`, merged as
`24371d8bf3289dad631c2986f44865794897f32c`. Its separate ARO-03 contract and route-test-selection
recovery is PR #4789 at head `c5f4fab08d58b5efb8d52a457bfa9eaf555824bd`, merged as
`989a8d73d52b75c3a038ba1d3f93c78e03d98065`. These delivery facts do not create a producer fact,
typed navigation, browser UI, accessibility proof, owner-pilot result, or `ready_to_try` fact.
