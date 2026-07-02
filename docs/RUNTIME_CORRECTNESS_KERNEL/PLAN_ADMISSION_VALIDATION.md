---
name: Plan Admission Validation
description: A plan-admission stage validating R1–R5 (post-transform validation, gated-effect authority+receipt ordering, resolvable verify targets, budget-sum + enforced plan-level wall-clock timeout, DAG cycle check) that every plan passes before execution
task_id: KERNEL-09
source_anchor: "docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: §3 decomposition model, I-A4"
parent_capability: RUNTIME_CORRECTNESS_KERNEL
prerequisites: [KERNEL-07]
depends_on: [STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN.md]
can_parallelize_with: []
---

# Plan Admission Validation

## Purpose

Planner output (`app/planner/`, `PLANNER_SYSTEM_PROMPT` in `app/planner/prompts.py` requests JSON by
prompt text only) is consumed by the orchestrator executor without schema validation; invalid plans
surface at step execution — the most expensive point. Orchestrator v2
(`app/orchestrator/v2_runtime.py :: OrchestratorV2`) has per-step retry/timeout and a `_validate_plan`
that checks only ids/dependencies/agent-tool presence (approx. line 739 at audit time). Audit
invariant **I-A4** (bounded execution) and §3 decomposition model require a real admission stage.

**Anchor correction vs. audit:** the audit says v2 has "NO plan-level wall-clock timeout." In fact
`run_plan` already computes an opt-in `deadline` from `tool_settings["plan_timeout_seconds"]`
(approx. lines 215–216, enforced at 237–253) — but it is opt-in and off by default. This task makes a
plan-level timeout **mandatory and enforced by default**, and adds the R1–R5 admission checks that
`_validate_plan` does not perform today.

## What This Task Does

Add a plan-admission stage — extend `_validate_plan` / add an admission function that every plan
passes through in `run_plan` before scheduling — validating, over the existing `Plan`/`PlanStep`
shapes (`app/planner/schema.py`; **extend, do not fork**):

- **R1** every `llm_transform`-class step is followed by a validation step before any consumer.
- **R2** governed-effect steps are preceded by an authority check and followed by receipt emission.
- **R3** plan admissible only if leaf steps have resolvable verify targets.
- **R4** the sum of per-step budgets ≤ the plan budget, and a plan-level wall-clock timeout exists
  and is enforced by default (not only when `plan_timeout_seconds` is supplied).
- **R5** DAG only — a cycle check at admission (today `DependencyGraph` / `_validate_step` explicitly
  *pass* on forward references and never detect cycles, approx. lines 126–150 and the `_validate_step`
  `pass` branch).

Reuse KERNEL-07's `constrained_completion(schema_ref)` so the planner's JSON output is
schema-validated at admission rather than trusted from prompt text.

**Scope honestly:** the current executor is `MockPlanExecutor`-level (`app/orchestrator/executor.py`).
The admission layer still lands as the contract *all* plans pass through, with the mandatory
plan-level timeout wired into the real `run_plan` loop so it holds regardless of executor maturity.

## Concretely

```bash
pytest -q tests/orchestrator/test_plan_admission.py
pytest -q tests/orchestrator/test_orchestrator_runs_steps.py   # existing runs stay green
```

## Why This Matters

Plan-schema drift and unbounded runs are detected at the most expensive point today (step
execution). Admission moves detection to the cheapest point and guarantees every plan is a DAG with
bounded budget and an enforced wall-clock, so a malformed or runaway plan cannot consume the runtime.

## Acceptance Criteria

- [ ] R1/R2/R3/R5 admission checks reject non-conforming plans before scheduling (post-transform
      validation ordering, gated-effect authority+receipt ordering, resolvable leaf verify targets,
      cycle detection).
      Verify: `tests/orchestrator/test_plan_admission.py::test_admission_rejects_r1_r2_r3_r5_violations`
- [ ] R4 budget: a plan whose per-step budget sum exceeds the plan budget is inadmissible.
      Verify: `tests/orchestrator/test_plan_admission.py::test_budget_sum_bounded`
- [ ] Enforcement AC: a plan-level wall-clock timeout is enforced by default from the production run
      entrypoint — the test drives `OrchestratorV2.run_plan()` (the real run loop) with a step that
      overruns and asserts the plan halts with `plan_timeout`, without relying on an opt-in setting.
      Verify: `tests/orchestrator/test_plan_admission.py::test_plan_timeout_enforced_from_run_plan`
- [ ] Every admitted plan is a validated artifact: planner JSON passes schema validation at
      admission (via the KERNEL-07 utility), not by prompt convention.
      Verify: `tests/orchestrator/test_plan_admission.py::test_plan_schema_validated_at_admission`

## How to Verify (Pre-Merge)

1. `pytest -q tests/orchestrator/test_plan_admission.py tests/orchestrator/test_orchestrator_runs_steps.py tests/orchestrator/test_pipeline_executes_plan.py`
2. Full `pytest -q -m "not pg"` (orchestrator run loop change); `ruff check app tests`.

## Out of Scope

- Building a real (non-mock) planner or executor; this task lands the admission contract + timeout.
- Event-topic schemas (KERNEL-08); the shared constrained-completion utility itself (KERNEL-07).

## Related Docs

- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: §3 decomposition model, I-A4`
- `docs/ARCHITECTURE.md` (orchestration bounded-execution description at promotion)

## Related GitHub Issues

One bounded issue. TCD hint: Sonnet / high effort (admission contract over the real run loop + an
enforced-by-default timeout with a production-entrypoint proof). Escalate to Opus if wiring the
mandatory timeout requires restructuring the `run_plan` scheduling loop beyond the deadline branch.
