---
name: Advance Delivery Runs Deterministically
description: Add a reducer and bounded adapters that advance compiled delivery plans without routine model coordination.
task_id: DDO-04
github_issue: 4167
source_anchor: docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md :: Architecture reconciliation after DDO-03
parent_capability: Deterministic Delivery Orchestration
prerequisites: [DDO-01, DDO-03]
depends_on: [RUN_INDEPENDENT_ISSUE_FAST_LANE.md, COMPILE_IMMUTABLE_DELIVERY_PLANS.md]
can_parallelize_with: []
recommended_capability: "Codex Sol / high"
capability_rationale: "Explicit state machine spanning claims, workers, CI, review, merge, and closure."
---

# Advance Delivery Runs Deterministically

## Purpose

Replace the prompt-driven plan/dispatch/wait/verify loop with one deterministic transition
function while keeping implementation, diagnosis, and independent review bounded and agentic.

## What This Task Does

- Implements the reducer states and legal transitions for plan admission, claim, worker start,
  implementation result, CI, review, repair, verified delivery, blocking, pause, resume, cancel,
  and supersession.
- Emits typed effect requests but performs no effect inside the reducer.
- Adds adapters over existing claim, worktree, CI-wait, review, verified-merge, and closure paths.
- Routes valid structured review severity deterministically.
- Defines the provider-neutral `worker-context-pack.v1`, `worker-invocation.v1`, `worker-result.v2`,
  and `WorkerRuntimePort` seam before any Codex- or Claude-specific adapter.
- Defines `DeliveryAcceptanceProfile.v1` before reducer terminality or downstream
  request/preview/approval code can depend on it.
- Adds `DeliveryReceipt.v2` for immutable acceptance-profile and supersession evidence while
  preserving canonical read support for delivered `DeliveryReceipt.v1`.
- Uses durable invocation correlations so a worker result cannot attach to another Issue/run/head,
  and free-form worker text can never drive a reducer transition.

## Concretely

An accepted structured implementation result advances to CI wait; a new head invalidates old
CI/review evidence; a valid P2 emits a known-defect disposition effect; a malformed verdict blocks;
an independent completed issue opens the next wave without a coordinator model turn. Pause, resume,
cancel, and supersede arrive as authenticated version-bound events, never prompt interpretations.

## Why This Matters

This slice captures most of the 80% deterministic-coordination target without yet requiring the
full durable outbox binding.

## Acceptance Criteria

- [ ] The reducer is a pure transition function with an exhaustive state/event matrix.
  - Verify: `tests/builderops/test_delivery_orchestration_contracts.py::test_reducer_transition_matrix_is_exhaustive`.
- [ ] Duplicate events are no-ops and stale run versions or head SHAs fail closed.
  - Verify: `tests/builderops/test_delivery_orchestration_contracts.py::test_duplicate_and_stale_events_cannot_advance`.
- [ ] Worker, CI, review, repair, merge, and closure effects are emitted only after their named
  prerequisites.
  - Verify: `tests/builderops/test_delivery_orchestration_contracts.py::test_effects_require_exact_prerequisites`.
- [ ] Valid structured P2 routes to one deferred disposition without synchronous repair; every
  protected/invalid/P0/P1 outcome blocks.
  - Verify: `tests/builderops/test_delivery_orchestration_contracts.py::test_review_severity_routes_fail_closed`.
- [ ] Existing production adapters are invoked through their governing scripts/services rather
  than reimplemented.
  - Verify: `tests/builderops/test_delivery_orchestration_contracts.py::test_runner_uses_existing_claim_wait_and_verified_closure_paths`.
- [ ] A two-wave fixture advances without coordinator model decisions between terminal worker
  receipts.
  - Verify: `tests/builderops/test_delivery_orchestration_contracts.py::test_independent_waves_advance_without_model_coordination`.
- [ ] Context pack, invocation, and result schemas bind the same run, plan, effect, Issue authority,
  exact head where relevant, contract hash, and invocation identity; provider/model/session data is
  confined to the invocation and result.
  - Verify: `tests/builderops/test_delivery_orchestration_contracts.py::test_worker_contracts_bind_one_authority_chain`.
- [ ] The worker port exposes idempotent start, inspect, heartbeat, interrupt, reattach,
  await-terminal, and cancel operations with typed not-started, starting-unknown, running, idle,
  terminal, unreachable, and cancelled states.
  - Verify: `tests/builderops/test_delivery_orchestration_contracts.py::test_worker_runtime_port_is_provider_neutral_and_exhaustive`.
- [ ] Free-form text, process exit status, or provider session state cannot directly advance the
  reducer; only a valid structured result can.
  - Verify: `tests/builderops/test_delivery_orchestration_contracts.py::test_unstructured_worker_output_cannot_advance`.
- [ ] Pause, resume, cancel, and supersede commands are authenticated, idempotent, version-fenced,
  and cannot claim to undo an already committed effect.
  - Verify: `tests/builderops/test_delivery_orchestration_contracts.py::test_lifecycle_controls_are_typed_fenced_and_effect_safe`.
- [ ] Missing, conflicting, or ambiguous authority rules resolve to a typed owner-decision state,
  while missing evidence/system state remains a distinct non-owner block.
  - Verify: `tests/builderops/test_delivery_orchestration_contracts.py::test_authority_ambiguity_and_system_blocks_are_distinct`.
- [ ] `DeliveryAcceptanceProfile.v1` is canonical, versioned, immutable, and resolves terminality
  only from explicit lower-level Issue/PR/CI/review/merge/closure evidence.
  - Verify: `tests/builderops/test_delivery_orchestration_contracts.py::test_acceptance_profile_is_canonical_and_evidence_bound`.
- [ ] `DeliveryReceipt.v2` binds the acceptance profile and superseding/superseded identities,
  round-trips canonically, and does not reinterpret valid v1 bytes.
  - Verify: `tests/builderops/test_delivery_orchestration_contracts.py::test_delivery_receipt_v2_is_additive_and_version_bound`.

## How to Verify (Pre-Merge)

- Run all named reducer, runner, and worker-runtime tests.
- Run focused dispatcher, CI-handoff, review, and verified-closure tests.
- Run `ruff check app tests` and `mypy app`.
- Run the state-machine review-before-CI convergence gate.

## Out of Scope

- New transaction/outbox storage.
- CKM initiation.
- Raising pilot concurrency.
- Selecting a preferred provider or provider-specific orchestration policy.
- Treating worker process/session state as delivery authority.

## Related Docs

- `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `.codex/skills/verification-and-closure/SKILL.md`
- `docs/audits/BUILDER_DELIVERY_AGENT_OS_2026-07-28.md`

## Related GitHub Issues

Live task: [#4167](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4167). DDO-01
[#4164](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4164) and DDO-03
[#4166](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4166) are delivered. #4167 is the next
serial implementation slice after this exact contract is merged, reconciled to the live Issue body,
and strict readiness validation passes.
