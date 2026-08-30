---
name: Prove Overview Browser and Accessibility States
description: Prove the merged Overview shell across hostile source states, layouts, accessibility paths, print, and JavaScript-off behavior.
task_id: ARO-07
github_issue: 4748
source_anchor: "docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Capability acceptance"
parent_capability: devUI Stage A Read-Only Overview
prerequisites: [ARO-06]
depends_on: [RENDER_READ_ONLY_OVERVIEW_SHELL.md]
can_parallelize_with: []
recommended_capability: "Codex Sol / high"
capability_rationale: "Fixture-driven browser validation spans source-state cross-products, identity continuity, accessibility, and no-effect proof."
execution_context: fresh_issue_agent
issue_local_helper_budget: 1
context_cost_estimate: high
complexity: high
verification_difficulty: high
defect_blast_radius: medium
review_gate: independent evidence review at exact tested SHA
---

# Prove Overview Browser and Accessibility States

## Purpose

Produce the hostile-state browser and accessibility receipt required before owner validation.

## Context

Parent: #4741

Produce the exact-SHA browser/accessibility receipt required before an owner pilot, without repairing
application behavior outside the shell issue's bounded scope. The proof consumes one frozen final
post-merge `main` SHA `M` containing delivered #4835 and #4836; it is not a production or owner-
acceptance receipt.

## Scope

- Run the complete hostile source-state and identity-continuity matrix at one exact final-main SHA.
- Prove responsive, keyboard, screen-reader, print, JavaScript-off, and no-effect behavior.
- Archive the bounded receipt/screenshots; route discovered defects to separate repair Issues.
- Authenticate the merged #4833 workflow run, artifact identity/digest, manifest, exact five-node
  JUnit inventory, browser URL/network/status observations, traces, screenshots, and per-node
  assertion inventory in one wrapper receipt, `devui-stage-a-exact-sha-state-matrix.v1`.
- Keep the source `devui-overview-browser-accessibility.v1` receipt self-describing for its own
  exact tested run. The downstream `devui-stage-a-read-only-owner-pilot.v1` ledger later binds
  this final-M artifact to independent production evidence; neither receipt claims deployment.

## What This Task Does

- Exercises the full layout, assistive-technology, degraded-source, and identity matrix.
- Proves no browser write, persistence, or reclassification behavior.
- Records exact-SHA artifacts without broadening into production repair.

## Concretely

One test run follows the same subject/evidence identity through all information depths under mixed
provider failure, narrow layout, 200% zoom, keyboard, print, and JavaScript-off states.

## Why This Matters

Static happy-path screenshots cannot prove source-state honesty or access to the full evidence path.

## Source Anchors

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Capability acceptance`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/RENDER_READ_ONLY_OVERVIEW_SHELL.md :: Acceptance Criteria`
- `docs/DEVUI.md :: Stage A completion gate`

## SBS Impact

- Primary subsystem: Builder System / devUI validation
- Secondary subsystem(s): browser harness and local API
- Write class: test/receipt evidence only
- Authority impact: none
- Persistence impact: test artifacts only
- Derived/rebuildable impact: validates the rebuildable shell
- Human knowledge impact: none
- Memory impact: none
- Retrieval/context impact: exact-source browser artifact and closed-set node inventory
- Sync/deployment impact: CI/browser validation only
- External boundary impact: none
- New or changed contract: exact-SHA browser/accessibility receipt
- Owner-doc impact: none until parent acceptance
- Transition debt impact: prevents optimistic visual closure
- Fitness rule impact: complete hostile-state/accessibility/no-effect matrix

## Constraints

This task adds or completes `tests/companion_ui/test_devui_overview_journeys.py` and archives only
the receipt/screenshot evidence required by the parent. A discovered production defect is filed
separately and blocks this proof; this validation task does not absorb its repair.

## Acceptance Criteria

- [ ] The exact five required #4833 nodeids execute once each at the frozen final-main `M`; the
      required, collected, and executed sets are equal, with no missing, renamed, duplicate,
      skipped, failed, or ambiguous entry.
  - Verify: `devui-stage-a-exact-sha-state-matrix.v1`, exact five-node JUnit/manifest inventory
- [ ] The real gateway Overview → server-owned visual Focus → return journey preserves subject and
      evidence continuity; browser interception, raw JSON visual substitution, and browser-built
      navigation are absent.
  - Verify: `tests/companion_ui/test_devui_overview_journeys.py::test_real_gateway_overview_focus_return_journey_preserves_subject_context_and_sha`
- [ ] Focus refusal, timeout, 404, HTTP/status failure, malformed response, request failure, page
      error, and console error paths render honest visual error state without alternate probes.
  - Verify: `tests/companion_ui/test_devui_overview_journeys.py::test_focus_api_failure_renders_honest_visual_error_without_url_probing`
- [ ] Exact Overview/Focus selectors, semantic/ARIA bindings, server identity, and transport-only
      `loading|loaded|error` state remain frozen; the full source-state matrix is not reclassified.
  - Verify: exact selector/state nodeids in `devui-stage-a-exact-sha-state-matrix.v1`
- [ ] Desktop, narrow, 200% zoom, keyboard, screen-reader/focus order, print, JavaScript-off,
      no-effect, no-egress, trace, screenshot, and checksum evidence pass with empty failure and
      unresolved-question lists.
  - Verify: `devui-stage-a-exact-sha-state-matrix.v1`

## How to Verify (Pre-Merge)

- Authenticate final `main` `M` and the merged #4833 workflow before dispatch.
- Dispatch #4833 against exactly `M`; reject any artifact whose closed-set required node inventory
  differs from the five nodeids defined by #4748.
- Independently re-download and hash the artifact, then validate JUnit, receipt, manifest, trace,
  screenshot, URL/network/status, page/console-error, and per-node assertion inventories together.
- Run `git diff --check`.
- Do not commit the wrapper receipt. Post it on #4748. A future owner pilot must bind this run's
  archived artifact through its own ledger contract and may not infer production acceptance.

## Suggested Validation

- Review the exact-head browser artifacts, token hash, and all named hostile fixtures together.

## Out of Scope

- Production repair, source/route/design changes, owner acceptance, or a mutation-capable workflow.

## Related Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/RENDER_READ_ONLY_OVERVIEW_SHELL.md`

## Source Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DEVUI.md`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/RENDER_READ_ONLY_OVERVIEW_SHELL.md`

## Applies learning (optional)

- Phase 1 audit supplies advisory hostile-state scenarios only.

## Related GitHub Issues

Filed as [#4748](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4748); delivered and closed
after the authenticated `devui-stage-a-exact-sha-state-matrix.v1` receipt at final-main `M`.
