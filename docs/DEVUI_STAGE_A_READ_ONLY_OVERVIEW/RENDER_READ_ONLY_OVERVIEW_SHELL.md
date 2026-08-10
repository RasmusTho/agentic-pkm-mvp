---
name: Render the Read-Only Overview Shell
description: Render the accepted server-declared Overview through a static local Yggdrasil shell without browser classification or persistence.
task_id: ARO-06
github_issue: 4747
source_anchor: "docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Cross-task invariants"
parent_capability: devUI Stage A Read-Only Overview
prerequisites: [ARO-03, ARO-04, ARO-05]
depends_on: [EXPOSE_LOCAL_OVERVIEW_GET_ROUTE.md, BIND_TYPED_OVERVIEW_NAVIGATION.md, VALIDATE_OVERVIEW_YGGDRASIL_DESIGN.md]
can_parallelize_with: []
recommended_capability: "Codex Sol / high"
capability_rationale: "A small visual surface still carries dense authority, degraded-state, responsive, and no-effect invariants."
execution_context: fresh_issue_agent
issue_local_helper_budget: 1
context_cost_estimate: high
complexity: high
verification_difficulty: high
defect_blast_radius: high
review_gate: independent visual-authority review plus exact-head browser CI
---

# Render the Read-Only Overview Shell

## Purpose

Implement only the accepted local read shell over the canonical Overview route.

## Context

Parent: #4741

Render the exact local Overview response as a calm read-only trust frame and three owner zones,
with typed navigation and progressive evidence, after the governed handoff is accepted.

## Scope

- Add one local static Overview entry and its bounded HTML/CSS/JavaScript assets.
- Render only the accepted route payload and ARO-05 visual treatment.
- Preserve typed navigation, progressive evidence, no-effect, and degraded-state behavior.

## What This Task Does

- Adds one bounded static entry and asset trio.
- Renders server-owned zones, evidence, limitations, and typed navigation.
- Enforces no command, credential, browser persistence, or classification path.

## Concretely

The browser fetches `/api/devui/overview` and renders its declared zones; it never reads raw
composition providers to decide where an item belongs.

## Why This Matters

The shell is the point where semantic drift becomes owner-visible and therefore needs a narrow scope.

## Source Anchors

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Cross-task invariants`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/VALIDATE_OVERVIEW_YGGDRASIL_DESIGN.md :: Acceptance Criteria`
- `docs/DEVUI.md :: DEVUI-OVERVIEW-BOUNDARY — server-declared read model`

## SBS Impact

- Primary subsystem: Builder System / devUI browser shell
- Secondary subsystem(s): local API and typed Focus/SoI navigation
- Write class: read-only static presentation
- Authority impact: none; server declares and UI renders
- Persistence impact: none
- Derived/rebuildable impact: browser render of per-request projection
- Human knowledge impact: none
- Memory impact: none
- Retrieval/context impact: local Overview GET only
- Sync/deployment impact: local static assets/API application entry
- External boundary impact: none at runtime
- New or changed contract: local static Overview shell
- Owner-doc impact: none until capability acceptance
- Transition debt impact: replaces standalone-provider reconstruction with one read surface
- Fitness rule impact: no-classification, no-persistence, typed-link, asset tests

## Constraints

Production scope is `app/api/app.py` plus new bounded assets
`app/web/static/devui-overview.html`, `app/web/static/devui-overview.css`, and
`app/web/static/devui-overview.js`. Focused tests may be added under `tests/api/test_devui_api.py`
and `tests/companion_ui/test_devui_overview_journeys.py`. No other UI is modified.

## Acceptance Criteria

- [ ] The shell renders server-declared Now, Needs you, Ready to try, trust frame, limitations,
      evidence state, and typed roots without inspecting raw providers to reclassify items.
  - Verify: `tests/companion_ui/test_devui_overview_journeys.py :: test_shell_renders_server_declared_zones_without_reclassification`
- [ ] Only components/tokens accepted by ARO-05 are used; provenance and token hash remain traceable.
  - Verify: `tests/companion_ui/test_devui_overview_journeys.py :: test_shell_uses_accepted_yggdrasil_assets`
- [ ] Available typed references navigate locally with stable subject/evidence identity; unavailable
      references are non-links with the exact limitation.
  - Verify: `tests/companion_ui/test_devui_overview_journeys.py :: test_shell_preserves_typed_navigation_identity`
- [ ] The bundle exposes no command, credential, provider switch, POST request, local/session storage,
      IndexedDB, service-worker cache, or durable selection.
  - Verify: `tests/companion_ui/test_devui_overview_journeys.py :: test_shell_rejects_browser_side_effects`
- [ ] JavaScript-off and print remain honest, readable, and explicitly limited rather than false-empty.
  - Verify: `tests/companion_ui/test_devui_overview_journeys.py :: test_shell_javascript_off_and_print_states_are_honest`

## How to Verify (Pre-Merge)

- Run the five named browser tests plus the devUI API suite and static-asset contract checks.
- Run `git diff --check`; compare the rendered states to the accepted ARO-05 receipt.

## Suggested Validation

- Execute every focused API/browser target at the exact PR head and compare screenshots to ARO-05.

## Out of Scope

- Source/composer/route semantics, new components/tokens, Focus/SoI implementation, commands, or durable UI state.

## Related Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DESIGN_PRINCIPLES.md`
- `app/web/static/colors_and_type.css`

## Source Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DEVUI.md`
- `docs/DESIGN_PRINCIPLES.md`

## Applies learning (optional)

- None.

## Related GitHub Issues

Filed as blocked child [#4747](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4747) on
#4744/#4745 delivery and the accepted #4746 design receipt.
