---
name: Compile Immutable Delivery Plans
description: Compile approved initiation payloads and live snapshots into immutable plans or typed refusals without side effects.
task_id: DDO-03
github_issue: 4166
source_anchor: docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md :: Plan compiler
parent_capability: Deterministic Delivery Orchestration
prerequisites: [DDO-02]
depends_on: [DEFINE_CARRIER_NEUTRAL_DELIVERY_CONTRACTS.md]
can_parallelize_with: []
recommended_capability: "Codex Terra / high"
capability_rationale: "Pure compiler with clear inputs and property tests, but non-trivial dependency and refusal semantics."
---

# Compile Immutable Delivery Plans

## Purpose

Move scope resolution, readiness, dependency, overlap, and policy decisions out of coordinator
prompts and into a pure, testable compiler.

## What This Task Does

- Accepts one validated `DeliveryInitiation.v1` and an explicit live-authority snapshot.
- Resolves exact Issues, strict contracts, canonical pickup labels, source anchors, dependencies,
  priorities, risk classes, likely mutation overlap, and real parent relationships.
- Produces immutable waves and typed exclusions/refusals.
- Supports exact issue sets without requiring a parent.
- Proves compilation performs no external or BuilderOps mutations.

The deployed installation has one owner/operator. Admission therefore uses the smallest correct
authority model for that setting: deterministic consistency checks over one explicit snapshot, not
multi-principal trust, signatures, consensus, Byzantine evidence, or distributed hardening.

## Concretely

The versioned `delivery-plan-compiler.v2` recompiles identical inputs into byte-identical
`DeliveryPlan.v1` values. A changed Issue body, label, dependency, or linked PR head changes the
input digest and requires a new plan; it never silently updates the prior plan.

## Compiler Contract Surface

- `DeliveryPlanningSnapshot.v2` carries exact live Issue authority plus immutable, versioned
  resolution evidence for every Source Anchor and `Verify:` target.
- Resolution evidence binds the exact Issue authority and contract hash, declared target,
  resolver/version, resolved authority/content hash, and observation chronology.
- The compiler consumes that evidence without filesystem, GitHub, dispatcher, BuilderOps, CKM,
  carrier, or provider access. Missing, duplicate, mismatched, or stale evidence produces a typed
  refusal and cannot enter an executable wave.
- Executable pickup authority is canonical and fail-closed: the Issue is open, carries exactly one
  `agent:*` state and that state is `agent:ready`, carries exactly one canonical type and priority
  label, the snapshot priority equals the live priority label, and the authority observation is no
  older than the approved initiation.
- A satisfied dependency present in the same snapshot is accepted only when that live authority is
  closed and delivered. A satisfied dependency outside the snapshot requires one frozen,
  versioned, hash-bound record binding the dependency identity and contract hash to closed
  authority evidence. Missing or contradictory proof is a typed refusal.
- The compiler and governed Issue intake share one pure canonical validator for repository paths,
  anchors, test targets, doc/roadmap writebacks, and versioned runtime-receipt identities; each
  criterion's Verify-target collection must be non-empty, unique, and fully resolvable.
- Facts already refused by those admission checks cannot exclude an otherwise eligible peer through
  mutation-overlap analysis.
- Snapshot evidence is part of the canonical input digest. Changed evidence creates a new plan
  identity rather than mutating a prior plan.

## Recovery Contract

The earlier `delivery-plan-compiler.strict-contract-admission.v1` mechanism exhausted its two
standard plus two capability-escalated repair attempts on PR #4218 at
`87278ed21d4d9a3c0eb34fa6558bd9b7e68602d1`. That history remains closed and is not reset.

The bounded replacement is
`delivery-plan-compiler.single-owner-authority-admission.v2`. It replans admission around canonical
pickup authority and minimal dependency-delivery proof; it is not a renamed v1 point fix. BuilderOps
LearningSignal `lrn_20260728092503_9b4c5db9` records the upstream omission.
Both the replacement compiler and its planning snapshot have v2 identities, so v1 and v2 admission
semantics cannot share an input digest or plan identity.

## Why This Matters

The compiler removes a large model-coordination cost while making every admission and exclusion
explainable before effects begin.

## Acceptance Criteria

- [ ] Identical initiation and snapshot inputs produce byte-identical plans.
  - Verify: `tests/builderops/test_delivery_plan_compiler.py::test_compiler_is_deterministic`.
- [ ] Missing Verify targets, stale delivery, dependency blocks, overlap, authority ambiguity, and
  malformed SBS impact produce typed refusals.
  - Verify: `tests/builderops/test_delivery_plan_compiler.py::test_compiler_refuses_unexecutable_scope_with_typed_reasons`.
- [ ] Explicit sets and real parent sets compile without conflating parent closure.
  - Verify: `tests/builderops/test_delivery_plan_compiler.py::test_compiler_separates_exact_set_from_parent_closure`.
- [ ] Compiler execution is mutation-free across GitHub, dispatcher, filesystem worktrees,
  BuilderOps, and CKM adapters.
  - Verify: `tests/builderops/test_delivery_plan_compiler.py::test_compiler_has_no_effect_adapter_access`.
- [ ] Property tests preserve wave dependency order and the maximum-parallel policy.
  - Verify: `tests/properties/test_delivery_plan_compiler.py::test_compiled_waves_preserve_dependencies_and_budget`.
- [ ] Conflicting canonical agent-state labels fail closed with a typed reason.
  - Verify: `tests/builderops/test_delivery_plan_compiler.py::test_compiler_refuses_conflicting_agent_labels`.
- [ ] Missing or duplicate canonical type and priority labels fail closed with typed reasons.
  - Verify: `tests/builderops/test_delivery_plan_compiler.py::test_compiler_refuses_missing_or_duplicate_type_and_priority_labels`.
- [ ] Snapshot priority that disagrees with the live priority label fails closed with a typed
  reason.
  - Verify: `tests/builderops/test_delivery_plan_compiler.py::test_compiler_refuses_priority_snapshot_label_mismatch`.
- [ ] Same-snapshot dependency satisfaction contradicting open, ready, or undelivered live
  authority fails closed.
  - Verify: `tests/builderops/test_delivery_plan_compiler.py::test_compiler_refuses_contradictory_internal_dependency_satisfaction`.
- [ ] External dependency satisfaction without minimal immutable hash-bound authority evidence
  fails closed.
  - Verify: `tests/builderops/test_delivery_plan_compiler.py::test_compiler_refuses_unproven_external_dependency_satisfaction`.
- [ ] The v2 compiler and planning snapshot identities prevent v1 and v2 semantics from sharing an
  input or plan identity.
  - Verify: `tests/builderops/test_delivery_plan_compiler.py::test_compiler_v2_versions_prevent_v1_identity_reuse`.

## How to Verify (Pre-Merge)

- Run all eleven named tests.
- Run focused contract tests from DDO-02.
- Run the focused strict-contract parity tests in
  `tests/governance/test_known_defects_registry.py`.
- Run `ruff check app tests` and `mypy app`.

## Out of Scope

- Claims, worker launches, waits, merges, or closure.
- Durable journaling.
- A durable initiation or dependency-evidence carrier.
- CKM initiation UI.
- Multi-operator, multi-principal, signature, consensus, Byzantine, or distributed trust design.

## Related Docs

- `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md`
- `.codex/skills/_shared/ISSUE_CONTRACT.md`

## Related GitHub Issues

Live task: [#4166](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4166), dependent on completed
DDO-02 [#4165](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4165).
