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

Produce the post-merge exact-SHA browser/accessibility receipt required before an owner pilot,
against final `main` commit `M` containing the accepted #4835 and #4836 changes, without repairing
application behavior outside the shell issue's bounded scope. The required #4833 browser proof at
the published #4836 candidate ref is a separate pre-merge gate; it is neither this later `M` proof
nor replaceable by it.

## Scope

- Before #4836 merges, dispatch the closed #4833/#4842 exact-ref five-node browser-proof workflow
  against the published #4836 candidate ref and retain its exact candidate receipt as the required
  pre-merge gate.
- After the accepted #4835 and #4836 changes merge, run the complete hostile source-state and
  identity-continuity matrix at final `M`, and bind this #4748 receipt to both `M` and the distinct
  authenticated candidate-proof receipt.
- Prove responsive, keyboard, screen-reader, print, JavaScript-off, and no-effect behavior.
- Archive the bounded receipt/screenshots; route discovered defects to separate repair Issues.

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
- Retrieval/context impact: fixed local source fixtures
- Sync/deployment impact: CI/browser validation only
- External boundary impact: none
- New or changed contract: exact-SHA browser/accessibility receipt
- Owner-doc impact: none until parent acceptance
- Transition debt impact: prevents optimistic visual closure
- Fitness rule impact: complete hostile-state/accessibility/no-effect matrix

## Constraints

This task adds or completes `tests/companion_ui/test_devui_overview_journeys.py` and archives only
the receipt/screenshot evidence required by the parent. A discovered production defect is filed
separately and blocks this proof; this validation task does not absorb its repair. No earlier #4747
SHA, pre-merge subset, or unrelated post-merge run may substitute for `M`; conversely, no `M` run
may substitute for the required exact published #4836 candidate proof before that candidate merges.

## Acceptance Criteria

- [ ] Desktop, narrow, 200% zoom, keyboard, screen-reader naming/focus order, print, and
      JavaScript-off journeys pass at one exact SHA.
  - Verify: `tests/companion_ui/test_devui_overview_journeys.py :: test_overview_accessibility_and_layout_matrix`
- [ ] Complete-empty, partial, stale, missing, refused, unsupported, unlinked, many-at-once, and
      mixed-provider fixtures retain distinct source semantics.
  - Verify: `tests/companion_ui/test_devui_overview_journeys.py :: test_overview_source_state_matrix`
- [ ] One selected subject preserves identical zone, source, evidence, limitation, and typed-root
      identity from glance through inspect and navigation.
  - Verify: `tests/companion_ui/test_devui_overview_journeys.py :: test_overview_identity_survives_all_information_depths`
- [ ] Hostile browser instrumentation proves no write request, credential, local/session storage,
      IndexedDB, service-worker cache, or browser classification.
  - Verify: `tests/companion_ui/test_devui_overview_journeys.py :: test_overview_browser_has_no_effect_or_reclassification`
- [ ] Receipt names exact final `M`, the separately authenticated pre-merge #4833/#4842 #4836
      candidate-proof receipt, fixture versions, token SHA-256, screenshots, accessibility results,
      failures, and unresolved visual questions.
  - Verify: runtime receipt: devui-overview-browser-accessibility.v1

## How to Verify (Pre-Merge)

- Before #4836 merge, dispatch the exact-ref browser workflow from #4833/#4842 against the published
  #4836 candidate ref and authenticate its five-node artifact. After final `M` exists, run the
  complete Overview browser module and exact focused API/producer regression modules at `M`, linking
  the later #4748 receipt to that candidate artifact without conflating their roles.
- Attach deterministic screenshot and accessibility artifacts to the exact-head receipt.
- Run `git diff --check`.

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

Filed as blocked child [#4748](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4748) after the
required exact published #4836 candidate proof through the closed #4833/#4842 workflow and on final
post-merge `main` commit `M` containing #4835 and #4836. The two receipts have distinct gates:
neither substitutes for the other. #4747 remains open/blocked and cannot supply a substitute SHA.
