---
name: Run the Read-Only Owner Pilot
description: Validate that the owner can answer the three Stage A questions from the exact read-only shell without false authority or durable acceptance.
task_id: ARO-08
github_issue: 4749
source_anchor: "docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Capability acceptance"
parent_capability: devUI Stage A Read-Only Overview
prerequisites: [ARO-07]
depends_on: [PROVE_OVERVIEW_BROWSER_ACCESSIBILITY.md]
can_parallelize_with: []
recommended_capability: "Owner walkthrough with Codex Terra / medium evidence capture"
capability_rationale: "The final check is an operator usability receipt over fixed read-only behavior, not implementation or an authority decision."
execution_context: fresh_issue_agent
issue_local_helper_budget: 0
context_cost_estimate: medium
complexity: medium
verification_difficulty: high
defect_blast_radius: low
review_gate: owner-acknowledged exact-SHA validation receipt
---

# Run the Read-Only Owner Pilot

## Purpose

Validate the three owner questions on the exact proven read-only shell.

## Context

Parent: #4741

Verify on one exact SHA and controlled source fixtures that the owner can answer **What should I
understand now?**, **Where is my authority actually needed?**, and **What is truly ready to try?**
without opening standalone source UIs or creating a durable acceptance state.

## Scope

- Run five predefined read-only owner scenarios over stable local fixtures and one exact SHA.
- Record answers, evidence path, source conditions, reconstruction steps, and dispositions.
- Return discovered defects/gaps to their owning blocked contract without implementing repairs.

## What This Task Does

- Runs the predefined three-zone, degraded-state, navigation, and no-durable-decision scenarios.
- Captures exact answers and reconstruction burden at one SHA.
- Hands parent closure forward only if every disposition passes.

## Concretely

The owner answers Now, Needs you, and Ready to try from the shell; a withdrawn zone is reported as
withdrawn with its source reason, never as empty or completed.

## Why This Matters

The final outcome is reduced truthful reconstruction, which repository tests alone cannot attest.

## Source Anchors

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Capability acceptance`
- `docs/DEVUI.md :: Completion gate`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/PROVE_OVERVIEW_BROWSER_ACCESSIBILITY.md :: Acceptance Criteria`

## SBS Impact

- Primary subsystem: Builder System / devUI owner validation
- Secondary subsystem(s): none
- Write class: owner-validation receipt only
- Authority impact: none; the pilot creates no decision or acceptance state
- Persistence impact: validation receipt only
- Derived/rebuildable impact: validates one exact rebuildable shell SHA
- Human knowledge impact: none
- Memory impact: none
- Retrieval/context impact: stable local fixtures only
- Sync/deployment impact: none
- External boundary impact: named owner walkthrough
- New or changed contract: final owner-pilot receipt
- Owner-doc impact: supplies evidence for later current-state reconciliation
- Transition debt impact: verifies reduction in standalone-UI reconstruction
- Fitness rule impact: three-zone answerability and no-durable-decision checks

## Constraints

This task owns the parent-validation receipt only. It changes no production code. Any defect,
source-authority gap, design gap, or inaccessible journey is filed separately and blocks the pilot.

## Acceptance Criteria

- [ ] For each zone, the receipt records the exact answer, evidence path, source conditions, elapsed
      reconstruction steps, and pass/fail disposition.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] The owner identifies every degraded/withdrawn state without reading it as empty, healthy,
      decided, delivered, or ready.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] Needs-you never presents a technical block and Ready-to-try never follows merge/done/closure
      without the accepted explicit source facts.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] Focus/optional SoI navigation preserves subject/evidence context or is visibly unavailable;
      no standalone subsystem UI is required for the tested answers.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] The pilot creates no tried/accepted/dismissed state, task, command, provider session, or write receipt.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1

## How to Verify (Pre-Merge)

- Confirm the ARO-07 receipt and exact SHA, then run the five named pilot checks.
- Post the signed/acknowledged result and any blockers to the parent; do not repair them here.

## Suggested Validation

- Validate every named pilot scenario against the exact ARO-07 receipt and SHA.

## Out of Scope

- Code/doc repair, owner action execution, durable feedback state, analytics, or broader adoption.

## Related Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DEVUI.md`

## Source Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DEVUI.md`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/PROVE_OVERVIEW_BROWSER_ACCESSIBILITY.md`

## Applies learning (optional)

- None.

## Related GitHub Issues

Filed as blocked child [#4749](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4749) on #4748's
exact browser/accessibility receipt and stable local fixtures.
