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
- Resolves exact Issues, strict contracts, source anchors, dependencies, priorities, risk classes,
  likely mutation overlap, and real parent relationships.
- Produces immutable waves and typed exclusions/refusals.
- Supports exact issue sets without requiring a parent.
- Proves compilation performs no external or BuilderOps mutations.

## Concretely

Recompiling identical inputs produces byte-identical `DeliveryPlan.v1`. A changed Issue body, label,
dependency, or linked PR head changes the input digest and requires a new plan; it never silently
updates the prior plan.

## Compiler Contract Surface

- `DeliveryPlanningSnapshot.v1` carries exact live Issue authority plus immutable, versioned
  resolution evidence for every Source Anchor and `Verify:` target.
- Resolution evidence binds the exact Issue authority and contract hash, declared target,
  resolver/version, resolved authority/content hash, and observation chronology.
- The compiler consumes that evidence without filesystem, GitHub, dispatcher, BuilderOps, CKM,
  carrier, or provider access. Missing, duplicate, mismatched, or stale evidence produces a typed
  refusal and cannot enter an executable wave.
- The compiler and governed Issue intake share one pure canonical validator for repository paths,
  anchors, test targets, doc/roadmap writebacks, and versioned runtime-receipt identities.
- Snapshot evidence is part of the canonical input digest. Changed evidence creates a new plan
  identity rather than mutating a prior plan.

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

## How to Verify (Pre-Merge)

- Run the five named tests.
- Run focused contract tests from DDO-02.
- Run the focused strict-contract parity tests in
  `tests/governance/test_known_defects_registry.py`.
- Run `ruff check app tests` and `mypy app`.

## Out of Scope

- Claims, worker launches, waits, merges, or closure.
- Durable journaling.
- CKM initiation UI.

## Related Docs

- `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md`
- `.codex/skills/_shared/ISSUE_CONTRACT.md`

## Related GitHub Issues

Live task: [#4166](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4166), blocked on DDO-02
[#4165](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4165).
