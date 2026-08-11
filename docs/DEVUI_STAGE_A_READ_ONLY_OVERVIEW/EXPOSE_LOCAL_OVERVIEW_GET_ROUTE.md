---
name: Expose the Local Overview GET Route
description: Expose the delivered composer over one direct-loopback GET endpoint using live composition readers.
task_id: ARO-03
github_issue: 4744
source_anchor: "docs/plans/DEVUI_IMPLEMENTATION.md :: Stage A — see: coherent read-only devUI"
parent_capability: devUI Stage A Read-Only Overview
prerequisites: []
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

## Delivery status

Delivered by #4744 / PR #4772 at implementation head
`7b1f83d4a0b6bdd75071959c41146c70012a29d2` and merge
`24371d8bf3289dad631c2986f44865794897f32c`. The direct-loopback route calls the live composition
readers and the delivered composer without candidates. It delivers no producer enrichment, typed
navigation, browser UI, design, accessibility proof, or owner pilot.

## Purpose

Expose the accepted production Overview as one bounded direct-loopback GET endpoint.

## Context

Parent: #4741

Serve the production `devui-overview-view.v1` result at `/api/devui/overview` without adding a
write path, cache, browser classification, or alternate composer.

## Scope

- Add `/api/devui/overview` as a per-request projection over the live composition readers and the delivered composer.
- Reuse existing local admission and preserve all semantic provider/candidate state.
- Add no static assets, navigation destination, command, or write method.

## What This Task Does

- Reuses direct-loopback local admission, the live composition readers, and the delivered composer.
- Returns the exact semantic envelope per request and rejects every mutation method.

## Concretely

`GET /api/devui/overview` returns `devui-overview-view.v1`; a forwarded or non-local request is
rejected and `POST /api/devui/overview` is unavailable.

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

Implementation is limited to `app/api/routes/devui.py` and `tests/api/test_devui_api.py`. It reuses
the route's existing direct-loopback local-admission dependency and calls the live composition
readers plus the delivered composer without candidates.

## Acceptance Criteria

- [ ] Local direct and accepted proxy requests return exact `devui-overview-view.v1`; non-local or
      ambiguous forwarded identity is rejected.
  - Verify: `tests/api/test_devui_api.py :: test_overview_route_reuses_local_admission_and_exact_contract`
- [ ] POST, PUT, PATCH, and DELETE are unavailable and the route has no command or mutation dependency.
  - Verify: `tests/api/test_devui_api.py :: test_overview_route_is_get_only`
- [ ] Available, partial, refused, and mixed-provider inputs preserve provider identity,
      freshness, completeness, refusal, linkage, withdrawals, and limitations.
  - Verify: `tests/api/test_devui_api.py :: test_overview_route_preserves_semantic_provider_envelopes`
- [ ] The endpoint recomposes each request and creates no cache, store, session, or durable selection.
  - Verify: `tests/api/test_devui_api.py :: test_overview_route_is_rebuildable_and_stateless`
- [ ] The route calls ARO-02's production producer and then the delivered composer in the same
      request instead of reimplementing zone rules or relying on an unconnected composer test.
  - Verify: `tests/api/test_devui_api.py :: test_overview_route_uses_production_producer_and_delivered_composer`

## How to Verify (Pre-Merge)

- Run the five named tests and full `tests/api/test_devui_api.py`.
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

Delivered by [#4744](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4744) / PR #4772 after
the accepted no-source decision superseded #4743. Future candidate enrichment requires a separate
governed source contract.
