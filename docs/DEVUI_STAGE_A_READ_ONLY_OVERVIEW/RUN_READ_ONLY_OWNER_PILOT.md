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

After all prerequisites are receipted, verify on one final post-merge `main` commit `M`—containing
the accepted semantic patches from #4835 and #4836—and disposable test-only state that the owner can
answer **What should I
understand now?**, **Where is my authority actually needed?**, and **What is truly ready to try?**
without opening standalone source UIs or creating a durable acceptance state.

This is a future executable pilot contract, not evidence that the shell has been deployed or that a
pilot has passed. At the current live checkpoint #4835 is open/in progress and #4836 is open/blocked,
so `M`, a fresh #4748-at-`M` proof, and deployment/owner receipts do not yet exist. The live URL and
deployed SHA remain intentionally absent until those receipts supply them.

## Scope

- Run the five predefined owner scenarios against Demerzel production: Compose project `pkm-prod`,
  `PKM_ENVIRONMENT=prod`, and the Midgård prod vault. The current promotion ref is `main`; the
  `stable` ref is dormant. This task does not promote, deploy, restart, or change either ref.
- Obtain the exact deployed URL and SHA only from receipts for final `M`, including the separately
  authenticated pre-merge #4836 candidate proof through #4833/#4842, the later #4748 proof at `M`,
  and deployment.
  Require that SHA to agree across the current CI/review/deploy receipt, `/version`,
  `/api/health.version`, and the authenticated gateway marker before the journey begins.
- Consume #4835's value-free boolean-only production prerequisite receipt for repository binding and
  coupled credential presence; it is evidence of prerequisites, not of provisioning or deployment.
- Use a disposable, test-only state matrix classified and approved before the pilot. Optional
  `pkm-test` participation is allowed only after its disposable classification is proven; the matrix
  must never rely on an unclassified local fixture or real owner/prod data.
- Record answers, evidence path, source conditions, reconstruction steps, Playwright trace,
  screenshots, checksums, manifest, and disposition in the final structured pilot ledger.
  That `devui-stage-a-read-only-owner-pilot.v1` ledger is the downstream cross-run binding: it
  records `candidate_browser_receipt_id`, `candidate_github_sha`,
  `candidate_five_node_artifact_digest`, `final_browser_receipt_id`, and `final_github_sha`.
  Those fields bind the two strict browser receipts without adding cross-run fields to either
  `devui-overview-browser-accessibility.v1` receipt.
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

Prerequisites are strict and serial: (1) the #4833/#4842 exact-ref five-node workflow proves the
published #4836 candidate before that candidate merges; (2) accepted #4835 and #4836 changes merge
into final `M`; (3) fresh #4748 proof at `M` references, but does not replace, that candidate-proof
receipt; (4) this repaired source contract; (5) #4835's value-free boolean prerequisite receipt;
(6) Demerzel authentication and access; (7) #4747's deployed route and server-supplied Focus
selectors; (8) the receipt-sourced exact deployed SHA and URL; and (9) approved disposable-state
classification. The pilot must not be claimed or made ready from this document alone.

## Acceptance Criteria

- [ ] The pilot binds to final post-merge `main` commit `M` containing #4835 and #4836, consumes
      both the separately authenticated pre-merge #4836 candidate proof and fresh #4748 proof at
      `M`, and records their candidate receipt ID/SHA/five-node artifact digest and final receipt
      ID/SHA in the structured pilot ledger. It also proves equality across the current
      CI/review/deploy receipt, `/version`, `/api/health.version`, and gateway marker before the
      journey.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] The ledger records #4835's boolean-only repository/credential prerequisite result without
      exposing values, account identities, paths, or provisioning claims.
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
- [ ] The classified disposable test-only state matrix—using `pkm-test` only when its disposable
      status is proven—produces no effects, page or console errors, browser persistence/storage, or
      unauthorized writes; traces, screenshots, checksums, and manifest are durable and bound to the
      deployed identity.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] The owner separately acknowledges the concrete promotion-plan result and the later evidence
      result; neither acknowledgement is inferred from merge, deployment, or the other acknowledgement.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] The owner explicitly acknowledges the bounded result; the pilot creates no tried/accepted/
      dismissed state, task, command, provider session, or product/runtime write receipt.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] A current-state writeback to `docs/DEVUI.md` is proposed only after PASS and remains outside
      this task before that result.
  - Verify: doc writeback at `docs/DEVUI.md :: Current state and target`

## How to Verify (Pre-Merge)

- Confirm every strict prerequisite, including the pre-merge #4836 candidate proof via #4833/#4842,
  merged #4835/#4836 at `M`, fresh #4748-at-`M` proof linked to that candidate artifact, the repaired
  source contract, #4835's boolean receipt, Demerzel access, #4747 selectors, the receipt-sourced
  URL/SHA, and disposable-state classification.
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
after #4748. It awaits the pre-merge #4836 candidate proof via #4833/#4842, final post-merge `M`
containing #4835/#4836, a fresh #4748-at-`M` proof linked to that candidate artifact, the repaired
contract, #4835's boolean prerequisite receipt, Demerzel prod access, #4747 selectors, receipt-
sourced deployed URL/SHA, separate promotion/owner acknowledgements, and disposable-state
classification.
