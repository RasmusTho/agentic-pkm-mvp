---
name: Advance Delivery Runs Deterministically
description: Add a reducer and bounded adapters that advance compiled delivery plans without routine model coordination.
task_id: DDO-04
github_issue: 4167
source_anchor: docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md :: Delivery reducer
parent_capability: Deterministic Delivery Orchestration
prerequisites: [DDO-01, DDO-03]
depends_on: [RUN_INDEPENDENT_ISSUE_FAST_LANE.md, COMPILE_IMMUTABLE_DELIVERY_PLANS.md]
can_parallelize_with: []
---

# Advance Delivery Runs Deterministically

## Purpose

Replace the prompt-driven plan/dispatch/wait/verify loop with one deterministic transition
function while keeping implementation, diagnosis, and independent review bounded and agentic.

## What This Task Does

- Implements the reducer states and legal transitions for plan admission, claim, worker start,
  implementation result, CI, review, repair, verified delivery, blocking, and supersession.
- Emits typed effect requests but performs no effect inside the reducer.
- Adds adapters over existing claim, worktree, CI-wait, review, verified-merge, and closure paths.
- Routes valid structured review severity deterministically.
- Uses durable invocation correlations so a worker result cannot attach to another Issue/run/head.

## Concretely

An accepted implementation result advances to CI wait; a new head invalidates old CI/review
evidence; a valid P2 emits a known-defect disposition effect; a malformed verdict blocks; an
independent completed issue opens the next wave without a coordinator model turn.

## Why This Matters

This slice captures most of the 80% deterministic-coordination target without yet requiring the
full durable outbox binding.

## Acceptance Criteria

- [ ] The reducer is a pure transition function with an exhaustive state/event matrix.
  - Verify: `tests/builderops/test_delivery_reducer.py::test_reducer_transition_matrix_is_exhaustive`.
- [ ] Duplicate events are no-ops and stale run versions or head SHAs fail closed.
  - Verify: `tests/builderops/test_delivery_reducer.py::test_duplicate_and_stale_events_cannot_advance`.
- [ ] Worker, CI, review, repair, merge, and closure effects are emitted only after their named
  prerequisites.
  - Verify: `tests/builderops/test_delivery_reducer.py::test_effects_require_exact_prerequisites`.
- [ ] Valid structured P2 routes to one deferred disposition without synchronous repair; every
  protected/invalid/P0/P1 outcome blocks.
  - Verify: `tests/builderops/test_delivery_reducer.py::test_review_severity_routes_fail_closed`.
- [ ] Existing production adapters are invoked through their governing scripts/services rather
  than reimplemented.
  - Verify: `tests/builderops/test_delivery_runner.py::test_runner_uses_existing_claim_wait_and_verified_closure_paths`.
- [ ] A two-wave fixture advances without coordinator model decisions between terminal worker
  receipts.
  - Verify: `tests/builderops/test_delivery_runner.py::test_independent_waves_advance_without_model_coordination`.

## How to Verify (Pre-Merge)

- Run the six named reducer/runner tests.
- Run focused dispatcher, CI-handoff, review, and verified-closure tests.
- Run `ruff check app tests` and `mypy app`.
- Run the state-machine review-before-CI convergence gate.

## Out of Scope

- New transaction/outbox storage.
- CKM initiation.
- Raising pilot concurrency.
- Provider-specific orchestration policy.

## Related Docs

- `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `.codex/skills/verification-and-closure/SKILL.md`

## Related GitHub Issues

Live task: [#4167](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4167), blocked on DDO-01
[#4164](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4164) and DDO-03
[#4166](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4166).
