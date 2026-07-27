---
name: Run Independent Issues Through a Fast Lane
description: Deliver immediate coordination savings for explicit independent issue sets using existing primitives.
task_id: DDO-01
github_issue: 4164
source_anchor: docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md :: Immediate value
parent_capability: Deterministic Delivery Orchestration
prerequisites: []
depends_on: []
can_parallelize_with: [Define Carrier-Neutral Delivery Contracts]
---

# Run Independent Issues Through a Fast Lane

## Purpose

Deliver useful coordination-cost reduction before the durable reducer and CKM bridge exist.

## What This Task Does

- Adds an explicit independent issue-set scope that does not require a synthetic epic.
- Validates strict readiness, dependency independence, likely file/contract overlap, and a
  maximum-two-worker pilot budget before dispatch.
- Updates `deliver-issue-set`, the autonomous runner prompt, and the existing dispatch/run-state
  helpers so workers receive one bounded issue and return one compact terminal receipt.
- Forbids worker-to-worker messaging unless deterministic evidence invalidates independence.
- Consumes the structured severity and known-defect contracts from PRs #4159 and #4161 when merged;
  it does not reimplement them.

## Concretely

Given four ready independent bug Issues, the dry-run output identifies one explicit set, selects at
most two workers, emits isolated context packs, records why no coordination is required, and
contains no parent-closure effect. A synthetic issue number is neither required nor accepted as a
substitute for scope identity.

## Why This Matters

Independent bugfixes currently pay a coordination tax even though their only shared resource is the
coordinator. This slice removes that tax without waiting for new durability or CKM infrastructure.

## Acceptance Criteria

- [ ] Explicit issue sets compile and dispatch without a synthetic epic or parent-closure plan.
  - Verify: `tests/builderops/test_epic_dispatch.py::test_explicit_independent_issue_set_needs_no_synthetic_epic`.
- [ ] Admission rejects dependencies, likely shared mutation surfaces, migrations, authority
  ambiguity, and more than the configured worker cap.
  - Verify: `tests/builderops/test_epic_dispatch.py::test_fast_lane_rejects_non_independent_or_over_budget_sets`.
- [ ] Worker packs contain one Issue, one worktree/branch plan, exact verification targets, known
  constraints, and one terminal receipt schema without broad epic history.
  - Verify: `tests/builderops/test_epic_dispatch.py::test_fast_lane_context_pack_is_minimal_and_receipted`.
- [ ] Skill and runner prompt prohibit routine worker-to-worker coordination and route discovered
  overlap to a typed coordinator exception.
  - Verify: `tests/architecture/test_agent_skill_entrypoints.py::test_independent_fast_lane_has_no_routine_worker_coordination`.
- [ ] Structured review routing blocks invalid/P0/P1 outcomes and defers valid P2 without a
  synchronous repair/re-review loop.
  - Verify: `tests/ops/test_review_before_ci_gate.py::test_fast_lane_consumes_structured_severity_without_weakening_gates`.
- [ ] The dry-run and persisted run-state remain evidence-only and reconstructable from live
  authority.
  - Verify: `tests/builderops/test_epic_run_state.py::test_fast_lane_state_never_becomes_delivery_authority`.

## How to Verify (Pre-Merge)

- Run the six named tests.
- Run the focused epic dispatch/run-state and governance tests.
- Run `python3 scripts/lint_skills_consistency.py`.
- Run `ruff check app tests`.
- Run `git diff --check`.

## Out of Scope

- Durable reducer state.
- BuilderOps outbox integration.
- Automatic CKM initiation.
- Changing PR #4159 or PR #4161 ownership.
- Raising parallelism above two during the pilot.

## Related Docs

- `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md`
- `.codex/skills/deliver-issue-set/SKILL.md`
- `companion-ui/prompts/codex/deliver-epic-autonomous-runner.md`

## Related GitHub Issues

Live task: [#4164](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4164). It is one of two
initial ready slices and may run in parallel with DDO-02 (#4165).
