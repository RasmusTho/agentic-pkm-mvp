---
name: Run the Read-Only Owner Pilot
description: Run the future deployed-production owner pilot only after the exact browser-proof, deployment, and disposable-state receipts exist; it records answerability without false authority or durable acceptance.
task_id: ARO-08
github_issue: 4749
source_anchor: "docs/DEVUI.md :: Owner-experience acceptance criteria"
parent_capability: devUI Stage A Read-Only Overview
prerequisites: [ARO-07]
depends_on: [PROVE_OVERVIEW_BROWSER_ACCESSIBILITY.md]
can_parallelize_with: []
recommended_capability: "Owner walkthrough with Codex Terra / high evidence capture"
capability_rationale: "The final check is a production-bound, zero-effect usability receipt that joins exact deployment identity, browser proof, and owner acknowledgement without performing a deployment."
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

Run the three owner questions on the exact deployed, proven read-only shell without creating any
owner decision, acceptance, browser-persistence, or runtime-write state.

## Context

Parent: #4741

After all prerequisites are receipted, verify on one exact deployed SHA and disposable test-only
state that the owner can answer **What should I
understand now?**, **Where is my authority actually needed?**, and **What is truly ready to try?**
without opening standalone source UIs or creating a durable acceptance state.

This is a future executable pilot contract, not evidence that the shell has been deployed or that a
pilot has passed. The live URL and deployed SHA are intentionally absent until the #4747, #4748,
and deployment receipts supply them.

## Scope

- Run the five predefined owner scenarios against Demerzel production: Compose project `pkm-prod`,
  `PKM_ENVIRONMENT=prod`, and the Midgård prod vault. The current promotion ref is `main`; the
  `stable` ref is dormant. This task does not promote, deploy, restart, or change either ref.
- Obtain the exact deployed URL and SHA only from the #4747/#4748/deployment receipts. Require that
  SHA to agree across the current CI/review/deploy receipt, `/version`, `/api/health.version`, and
  the authenticated gateway marker before the journey begins.
- Use a disposable, test-only state matrix classified and approved before the pilot. It must not
  rely on a local fixture or real owner/prod data.
- Record answers, evidence path, source conditions, reconstruction steps, Playwright trace,
  screenshots, checksums, manifest, and disposition in the final structured pilot ledger.
- Return discovered defects/gaps to their owning blocked contract without implementing repairs.

## What This Task Does

- Runs the predefined three-zone, degraded-state, and no-durable-decision scenarios plus a real
  **Overview → server-supplied Focus link → return** Playwright journey.
- Captures exact answers and reconstruction burden at the receipt-sourced deployed SHA and URL.
- Proves zero effects: no page or console errors, browser persistence/storage, unauthorized writes,
  commands, provider sessions, or durable acceptance state.
- Hands parent closure forward only if every disposition passes.

## Concretely

The owner answers Now, Needs you, and Ready to try from the shell; a withdrawn zone is reported as
withdrawn with its source reason, never as empty or completed.

## Why This Matters

The final outcome is reduced truthful reconstruction, which repository tests alone cannot attest.

## Source Anchors

- `docs/DEVUI.md :: Owner-experience acceptance criteria`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Capability acceptance`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/PROVE_OVERVIEW_BROWSER_ACCESSIBILITY.md :: Acceptance Criteria`

## SBS Impact

- Primary subsystem: Builder System / devUI owner validation
- Secondary subsystem(s): none
- Write class: durable owner-validation evidence only; no product or runtime write
- Authority impact: none; the pilot creates no decision or acceptance state
- Persistence impact: validation receipt only
- Derived/rebuildable impact: validates one exact rebuildable shell SHA
- Human knowledge impact: none
- Memory impact: none
- Retrieval/context impact: receipt-sourced production URL with disposable test-only state only
- Sync/deployment impact: consumes an existing Demerzel production deployment receipt; performs no deployment
- External boundary impact: named owner walkthrough
- New or changed contract: final owner-pilot receipt
- Owner-doc impact: supplies evidence for later current-state reconciliation
- Transition debt impact: verifies reduction in standalone-UI reconstruction
- Fitness rule impact: three-zone answerability and no-durable-decision checks

## Constraints

This task owns the parent-validation receipt only. It changes no production code and does not deploy,
promote, restart, or mutate production. Any defect, source-authority gap, design gap, inaccessible
journey, identity mismatch, effect, error, storage use, or unauthorized write is returned to its
owning blocked contract and blocks the pilot.

Prerequisites are strict and serial: (1) #4748 delivery and exact browser/accessibility receipt;
(2) this repaired source contract; (3) Demerzel authentication and access; (4) #4747's deployed
route and server-supplied Focus selectors; (5) the receipt-sourced exact deployed SHA and URL; and
(6) approved disposable-state classification. The pilot must not be claimed or made ready from this
document alone.

## Acceptance Criteria

- [ ] The pilot obtains its exact deployed URL and SHA from the #4747/#4748/deployment receipts and
      proves equality across the current CI/review/deploy receipt, `/version`,
      `/api/health.version`, and gateway marker before the journey.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] For each zone, the final structured ledger records the exact answer, evidence path, source
      conditions, elapsed reconstruction steps, and pass/fail disposition.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] The owner identifies every degraded/withdrawn state without reading it as empty, healthy,
      decided, delivered, or ready.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] Needs-you never presents a technical block and Ready-to-try never follows merge/done/closure
      without the accepted explicit source facts.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] A Playwright journey follows Overview to a server-supplied Focus link and returns while
      preserving subject/evidence context; no standalone subsystem UI is required for the tested
      answers.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] The disposable test-only state matrix produces no effects, page or console errors, browser
      persistence/storage, or unauthorized writes; traces, screenshots, checksums, and manifest
      are durable and bound to the deployed identity.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] The owner explicitly acknowledges the bounded result; the pilot creates no tried/accepted/
      dismissed state, task, command, provider session, or product/runtime write receipt.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] A current-state writeback to `docs/DEVUI.md` is proposed only after PASS and remains outside
      this task before that result.
  - Verify: doc writeback at `docs/DEVUI.md :: Current state and target`

## How to Verify (Pre-Merge)

- Confirm every strict prerequisite, including #4748, the repaired source contract, Demerzel access,
  #4747 selectors, the receipt-sourced URL/SHA, and disposable-state classification.
- Run the five named pilot checks and the Overview → Focus → return Playwright journey.
- Post the owner-acknowledged structured result and any blockers to the parent; do not repair them
  here. Only a PASS may trigger a separate current-state owner-doc writeback decision.

## Suggested Validation

- Validate every named pilot scenario, deployment-identity agreement, disposable-state boundary,
  no-effect evidence, and durable evidence manifest against the receipt-sourced deployed URL/SHA.

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

Filed as blocked child [#4749](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4749) serially
after #4748. It awaits the repaired contract, Demerzel prod access, #4747 selectors, #4748's exact
browser/accessibility receipt, receipt-sourced deployed URL/SHA, and disposable-state classification.
