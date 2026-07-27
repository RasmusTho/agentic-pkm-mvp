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
---

# Validate TCD and Recovery

## Purpose

Accept the capability on measured delivery outcomes rather than architecture claims.

## What This Task Does

- Captures a comparable baseline from recent issue-set delivery evidence.
- Runs one 4–8 Issue fast-lane pilot and one full-kernel pilot when suitable ready work exists.
- Runs the full crash/reconciliation matrix in a non-production environment.
- Compares deterministic transition share, coordinator turns/tokens, human interventions, worker
  starts, CI waits, repair rounds, lead time, duplicate effects, and defect outcomes.
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
- [ ] Existing CI, exact-head review, verified merge, closure, and escaped P0/P1 outcomes do not
  regress.
  - Verify: parent quality non-regression ledger.
- [ ] Parent acceptance, residual work, and owner-doc impact are resolved explicitly.
  - Verify: parent Issue checklist plus final owner-doc PR or a bounded follow-up Issue.

## How to Verify (Pre-Merge)

- Run the two named test modules and all DDO-02 through DDO-06 focused targets.
- Attach redacted runtime pilot receipts to the parent Issue.
- Compare baseline/pilot metrics using the checked-in metric definitions.
- Run current-head CI and the independent final review gate.

## Out of Scope

- Expanding pilot concurrency above two.
- Production deployment or stable promotion.
- Hiding missed targets by changing metric definitions after the run.
- Keeping the parent open for indefinite observation after repo-verifiable acceptance.

## Related Docs

- `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md`
- `AGENTS.md :: Total Cost of Development`
- `docs/development/DELIVERY_FEEDBACK_LOOP.md`

## Related GitHub Issues

Live task: [#4170](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4170), blocked on DDO-01
through DDO-06 (#4164–#4169). It owns the parent-closure handoff and final owner-doc promotion
decision.
