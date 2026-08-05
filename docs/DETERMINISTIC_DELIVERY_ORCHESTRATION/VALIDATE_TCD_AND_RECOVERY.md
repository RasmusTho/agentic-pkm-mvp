---
name: Validate TCD and Recovery
description: Prove staged coordination savings, recovery convergence, and quality non-regression before capability acceptance.
task_id: DDO-07
github_issue: 4170
source_anchor: docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md :: Capability acceptance
parent_capability: Deterministic Delivery Orchestration
prerequisites: [DDO-01, DDO-02, DDO-03, DDO-04, DDO-05, DDO-06]
depends_on: [RUN_INDEPENDENT_ISSUE_FAST_LANE.md, DEFINE_CARRIER_NEUTRAL_DELIVERY_CONTRACTS.md, COMPILE_IMMUTABLE_DELIVERY_PLANS.md, ADVANCE_DELIVERY_RUNS_DETERMINISTICALLY.md, BIND_DELIVERY_EFFECTS_TO_BUILDEROPS_RECONCILIATION.md, CONNECT_CKM_INITIATION_AND_DELIVERY_RECEIPTS.md]
can_parallelize_with: []
recommended_capability: "Codex Sol / high"
capability_rationale: "Cross-system acceptance, fault injection, and quality/TCD non-regression judgment."
---

# Validate TCD and Recovery

## Purpose

Accept the capability on measured delivery outcomes rather than architecture claims.

## What This Task Does

- Captures a comparable baseline from recent issue-set delivery evidence.
- Runs one 4–8 Issue fast-lane pilot and one full-kernel pilot when suitable ready work exists.
- Uses the seven observed scheduled bug selections (#4614, #4562, #4195, #4612, #4618, #4622,
  and #4611) as the explicit pre-change baseline, including stale contract, worker-start timeout,
  detached checkout collision, incomplete owner-doc closure, and complete terminal-chain outcomes.
- Runs a separate 4–8 Issue strict-serial scheduled `type:bug` pilot with Luna/low coordination and
  normal Terra/medium implementation, escalating capability only from recorded TCD risk evidence.
- Runs the full crash/reconciliation matrix in a non-production environment.
- Runs the worker-runtime conformance matrix against the native carrier and any optional candidate
  carrier.
- Compares deterministic transition share, coordinator turns/tokens, human interventions, worker
  starts, CI waits, repair rounds, lead time, duplicate effects, and defect outcomes.
- Validates that every pilot binds one immutable `DeliveryAcceptanceProfile.v1` and reports the
  lower-level evidence behind its terminal result.
- Produces the parent acceptance report and triggers owner-doc promotion only on success.

## Concretely

The report distinguishes model implementation cost from coordination cost. It rejects a result that
reduces coordinator tokens by adding worker churn, review loops, human recovery, duplicate effects,
or escaped blocking defects.

## Why This Matters

The purpose is lower total cost per accepted delivery, not a high automation percentage that moves
cost or risk elsewhere.

## Acceptance Criteria

- [ ] Baseline and pilot receipts use the same metric definitions and include every cost/quality
  field from the capability README.
  - Verify: `tests/builderops/test_delivery_tcd_receipt.py::test_baseline_and_pilot_metrics_are_comparable`.
- [ ] A 4–8 Issue fast-lane pilot runs with max parallel two, no synthetic epic, and no routine
  worker-to-worker coordination.
  - Verify: runtime pilot receipt linked on the parent Issue.
- [ ] The full reducer pilot shows at least 90% deterministic coordination transitions or records a
  bounded evidence-backed rejection of the target without weakening gates.
  - Verify: acceptance report linked on the parent Issue.
- [ ] Crash injection and recovery tests produce zero duplicate logical effects.
  - Verify: `tests/builderops/test_delivery_orchestration_recovery.py`.
- [ ] An `autonomous_bug_delivery_pilot.v1` receipt compares all seven baseline selections with the
  strict-serial pilot and binds every scheduler tick, lane/run/attempt, Issue, dispatcher claim,
  worker/thread, worktree generation, branch, PR/head/CI, merge, closure, owner-doc, and terminal
  receipt identity.
  - Verify: receipt linked on the parent Issue with source refs for each baseline and pilot run.
- [ ] Concurrent scheduler ticks and restart at lane claim, attempt genesis, preparation, claim,
  activation, PR, merge, owner-doc, and terminal receipt converge to one active attempt and zero
  duplicate workers, claims, PRs, merges, or closures.
  - Verify: `tests/builderops/test_delivery_orchestration_recovery.py::test_scheduled_bug_lane_restart_matrix_converges`.
- [ ] Detached project-worktree bootstrap and a pre-existing branch/worktree collision prove
  `prepared`→claim→same-generation `active` behavior; foreign work is observed/waited on and never
  adopted or overwritten.
  - Verify: `tests/builderops/test_delivery_worker_runtime.py::test_scheduled_bug_pilot_detached_and_collision_fixtures`.
- [ ] A merged PR with a missing owner-doc receipt keeps the same attempt/lane occupied, and exact
  receipt insertion lets #3604 closure recovery produce one terminal release.
  - Verify: `tests/dispatcher/test_closure_consumer.py::test_active_delivery_attempt_waits_for_owner_doc_receipt_before_lane_release` using
    `tests/dispatcher/fixtures/closure/merged_missing_owner_doc_4612.json` and
    `tests/dispatcher/fixtures/closure/merged_missing_owner_doc_4618.json`, plus the pilot receipt.
- [ ] Request → preview → exact approval is proven without preapproval mutation or stale-authority
  reuse.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_request_preview_approval_chain_is_exact_and_fresh`.
- [ ] Each run preserves one exact immutable acceptance-profile reference and hash across request,
  preview, initiation, initial reducer state, transitions/effects, and receipt; accepted/partial/
  blocked/failed/cancelled/superseded terminality is reconstructible from explicit
  Issue/PR/CI/review/merge/closure evidence.
  - Verify: `tests/builderops/test_delivery_acceptance_profiles.py::test_terminal_result_follows_immutable_profile_and_evidence`.
- [ ] Native worker execution passes the provider-neutral start/inspect/reattach/cancel/result and
  crash-boundary conformance matrix.
  - Verify: `tests/builderops/test_delivery_worker_runtime.py::test_native_worker_runtime_conformance_matrix`.
- [ ] Existing CI, exact-head review, verified merge, closure, and escaped P0/P1 outcomes do not
  regress.
  - Verify: parent quality non-regression ledger.
- [ ] Parent acceptance, residual work, and owner-doc impact are resolved explicitly.
  - Verify: parent Issue checklist plus final owner-doc PR or a bounded follow-up Issue.
- [ ] The owner can complete the request/preview/approve/follow/control/result flow from
  plain-language evidence, with a low-cost 3–5 minute captioned walkthrough recorded only after the
  surface is stable.
  - Verify: owner walkthrough receipt and linked training artifact on the parent Issue.

## How to Verify (Pre-Merge)

- Run the two named test modules and all DDO-02 through DDO-06 focused targets.
- Attach redacted runtime pilot receipts to the parent Issue.
- Compare baseline/pilot metrics using the checked-in metric definitions.
- Run current-head CI and the independent final review gate.

## Out of Scope

- Expanding pilot concurrency above two.
- Treating the generic max-parallel-two fast-lane profile as permission for more than one scheduled
  bug attempt, or enforcing the scheduled lane on unrelated direct manual pickup.
- Production deployment or stable promotion.
- Hiding missed targets by changing metric definitions after the run.
- Keeping the parent open for indefinite observation after repo-verifiable acceptance.
- Defining or revising `DeliveryAcceptanceProfile.v1`; DDO-04 owns the schema and this task validates
  its use.
- Making DBOS, Restate, Temporal, LangGraph, or another external workflow runtime a production
  dependency without a separately approved carrier decision.

## Optional durable-carrier proof

No external agent operating system is required for acceptance. After DDO-05 proves the native
semantics, a bounded DBOS proof may compare only durable sleep/resume and worker-carrier behavior.
The proof is accepted only if the exact canonical plan and reducer-authorized worker-launch effect
identity remain unchanged and carrier runs produce the same normalized delivery-domain result.
Every result must retain its complete invocation/carrier/provider/model/session/usage/provenance
envelope, whose values and bytes may differ. Replay never duplicates worker start, unknown-start
recovery converges, cancellation is typed, fencing still governs external effects, and no DBOS
workflow state becomes delivery authority. Failure or negative TCD evidence ends the proof without
delaying the native path.

## Related Docs

- `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md`
- `AGENTS.md :: Total Cost of Development`
- `docs/development/DELIVERY_FEEDBACK_LOOP.md`
- `docs/audits/AUTONOMOUS_BUG_DELIVERY_ARCHITECTURE_2026-08-05.md`

## Related GitHub Issues

Live task: [#4170](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4170), blocked on DDO-01
through DDO-06 (#4164–#4169). It owns the parent-closure handoff and final owner-doc promotion
decision.
