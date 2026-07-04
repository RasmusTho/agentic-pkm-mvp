"""Plan admission validation (KERNEL-09, #2771).

Every plan passes through :func:`admit_plan` *before scheduling* on **both**
production run loops — ``Orchestrator.run_plan`` (V1, the live default:
``ORCHESTRATOR_VERSION`` defaults to ``v1``, and ``app/agents/pipeline.py`` /
``app/cli`` construct ``Orchestrator()`` directly) and
``OrchestratorV2.run_plan``. Admission moves plan-shape and boundedness
failures from the most expensive detection point (step execution) to the
cheapest one (admission), per audit invariant I-A4 and the §3 decomposition
model of ``docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md``.

Checks (``docs/RUNTIME_CORRECTNESS_KERNEL/PLAN_ADMISSION_VALIDATION.md``):

- **schema** — the plan validates against the registered KERNEL-07 schema
  artifact (``planner.plan.v1``), not prompt convention.
- **R1** — every ``llm_transform``-class step is followed by a
  ``validation``-class step before any consumer.
- **R2** — every ``governed_effect``-class step is preceded by an
  ``authority_check``-class step and followed by ``receipt`` emission.
- **R3** — every leaf step has a resolvable verify target. A declared
  ``PlanStep.verify`` must resolve (recognized scheme, in-plan step for
  ``step:`` targets); undeclared steps fall back to the intrinsic per-kind
  target that maps onto the executor's real result shape
  (``app/orchestrator/executor.py :: MockPlanExecutor.execute_step``).
- **R4** — the sum of per-step budgets must not exceed the plan budget, and a
  positive plan-level wall-clock timeout must exist. The timeout is mandatory
  by default (``resolve_plan_timeout``); a plan-authored
  ``plan_timeout_seconds`` may only **lower** the effective bound, never raise
  it past the operator setting or ``DEFAULT_PLAN_TIMEOUT_SECONDS``.
- **R5** — the plan is a DAG: unknown/duplicate step references and dependency
  cycles are rejected (the legacy ``_validate_step`` explicitly passed on
  forward references and never detected cycles).

Timeout guarantee, stated precisely: the deadline gates **step submission** —
no new step is scheduled at or after the deadline, and the plan halts with
``plan_timeout``. Steps already in flight when the deadline passes are bounded
only by their own ``tool_timeout_seconds``; in-flight cancellation is a known,
separately tracked gap, not something this module claims to provide.

Scope of ``step_class`` (honest boundary): LLM-produced plans always carry
``step_class`` on every step — the planner-facing registered schema
(``planner.plan.output.v1``) requires it, so constrained decoding cannot omit
it. Legacy and code-built/deserialized plans without ``step_class``
declarations are admitted under the remaining rules only (schema, R3 intrinsic
targets, R4 budgets/timeout, R5 DAG); R1/R2 bind on declared classes and make
no security claim about undeclared steps.

Failure semantics are explicit and loud: any violation raises
:class:`PlanAdmissionError` naming the rule; there is no silent repair and no
partial admission.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Mapping, Set

from app.components.llm.constrained import ConstrainedCompletionError, validate_payload
from app.planner.plan_schema import PLAN_SCHEMA_REF
from app.planner.schema import Plan, PlanStep

logger = logging.getLogger(__name__)

#: Mandatory-by-default plan-level wall-clock budget (seconds). Neither absence
#: nor a non-positive value ever resolves to "unbounded", and a plan-authored
#: value can only lower the effective bound (see ``resolve_plan_timeout``).
DEFAULT_PLAN_TIMEOUT_SECONDS: float = 600.0

#: Recognized verify-target schemes for ``PlanStep.verify`` ("<scheme>:<target>").
#: ``result:`` targets a key of the step's own execution result; ``step:``
#: names another in-plan step that verifies this one; ``receipt:``/``event:``/
#: ``test:`` name durable artifacts outside the plan.
VERIFY_TARGET_SCHEMES: frozenset[str] = frozenset({"result", "step", "receipt", "event", "test"})

#: Intrinsic verify target per step kind for steps that do not declare one.
#: Each maps onto a key the executor actually emits for that kind
#: (``MockPlanExecutor.execute_step``), so the target is mechanically
#: resolvable against the step's result.
_INTRINSIC_VERIFY_BY_KIND: Mapping[str, str] = {
    "agent_call": "result:response",
    "tool_call": "result:result",
    "decision": "result:decision",
    "note": "result:note",
}


class PlanAdmissionError(Exception):
    """A plan failed admission. ``rule`` names the violated check."""

    def __init__(self, *, rule: str, reason: str) -> None:
        super().__init__(f"plan inadmissible ({rule}): {reason}")
        self.rule = rule
        self.reason = reason


def _positive_timeout(settings: Mapping[str, Any] | None) -> float | None:
    raw = settings.get("plan_timeout_seconds") if settings else None
    try:
        value = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        value = None
    if value is not None and value > 0:
        return value
    return None


def resolve_plan_timeout(
    operator_settings: Mapping[str, Any] | None,
    plan_settings: Mapping[str, Any] | None,
) -> float:
    """Return the effective plan-level wall-clock timeout in seconds.

    The operator bound is the orchestrator-level ``plan_timeout_seconds`` (or
    ``DEFAULT_PLAN_TIMEOUT_SECONDS`` when absent/non-positive). A plan-authored
    ``plan_timeout_seconds`` (from ``plan.context.tool_settings``) may only
    **lower** the effective bound — a plan cannot raise its own wall-clock
    budget past what the operator or the default allows; oversized values are
    clamped loudly. The return value is always positive: a plan without a
    wall-clock bound is not a state this function can produce.
    """
    operator_bound = _positive_timeout(operator_settings) or DEFAULT_PLAN_TIMEOUT_SECONDS
    plan_value = _positive_timeout(plan_settings)
    if plan_value is None:
        return operator_bound
    if plan_value > operator_bound:
        logger.warning(
            "plan-authored plan_timeout_seconds=%s exceeds the operator bound %ss; clamped",
            plan_value,
            operator_bound,
        )
        return operator_bound
    return plan_value


def admit_plan(plan: Plan, *, plan_timeout_seconds: float | None) -> Plan:
    """Run the full admission stage; raise :class:`PlanAdmissionError` on any violation."""
    _check_schema(plan)
    steps = list(plan.steps)
    _check_r5_dag(steps)  # R5 first: the ordering rules below need a sound DAG.
    transitive_deps = _transitive_dependencies(steps)
    _check_r1_transform_validation(steps, transitive_deps)
    _check_r2_governed_effects(steps, transitive_deps)
    _check_r3_leaf_verify_targets(steps, transitive_deps)
    _check_r4_budgets(plan, steps, plan_timeout_seconds)
    return plan


def _check_schema(plan: Plan) -> None:
    """Every admitted plan is a validated artifact against the registered schema."""
    try:
        payload = plan.model_dump(mode="json")
    except Exception as exc:  # non-JSON-serializable plan state is inadmissible
        raise PlanAdmissionError(
            rule="schema", reason=f"plan is not JSON-serializable: {exc}"
        ) from exc
    try:
        validate_payload(PLAN_SCHEMA_REF, payload)
    except ConstrainedCompletionError as exc:
        raise PlanAdmissionError(rule="schema", reason=exc.reason) from exc


def _check_r5_dag(steps: List[PlanStep]) -> None:
    """R5: DAG only — unique ids, known references, no cycles."""
    ids: Set[str] = set()
    for step in steps:
        if step.id in ids:
            raise PlanAdmissionError(rule="R5", reason=f"duplicate step id '{step.id}'")
        ids.add(step.id)
    for step in steps:
        for dep in step.depends_on or []:
            if dep not in ids:
                raise PlanAdmissionError(
                    rule="R5",
                    reason=f"step '{step.id}' depends on unknown step '{dep}'",
                )
    # Kahn's algorithm: anything not topologically orderable is in a cycle.
    remaining_deps: Dict[str, Set[str]] = {s.id: set(s.depends_on or []) for s in steps}
    dependents: Dict[str, Set[str]] = defaultdict(set)
    for step in steps:
        for dep in step.depends_on or []:
            dependents[dep].add(step.id)
    ready = [sid for sid, deps in remaining_deps.items() if not deps]
    ordered = 0
    while ready:
        sid = ready.pop()
        ordered += 1
        for dependent in dependents.get(sid, ()):  # release dependents
            remaining_deps[dependent].discard(sid)
            if not remaining_deps[dependent]:
                ready.append(dependent)
    if ordered != len(steps):
        cyclic = sorted(sid for sid, deps in remaining_deps.items() if deps)
        raise PlanAdmissionError(
            rule="R5",
            reason=f"dependency cycle among steps {cyclic}",
        )


def _transitive_dependencies(steps: List[PlanStep]) -> Dict[str, Set[str]]:
    """Map step id -> all (direct + transitive) dependency ids. Assumes a DAG."""
    deps_map: Dict[str, Set[str]] = {s.id: set(s.depends_on or []) for s in steps}
    memo: Dict[str, Set[str]] = {}

    def visit(sid: str) -> Set[str]:
        cached = memo.get(sid)
        if cached is not None:
            return cached
        acc: Set[str] = set()
        for dep in deps_map.get(sid, ()):  # R5 guarantees these exist and terminate
            acc.add(dep)
            acc |= visit(dep)
        memo[sid] = acc
        return acc

    return {s.id: visit(s.id) for s in steps}


def _check_r1_transform_validation(
    steps: List[PlanStep], transitive_deps: Dict[str, Set[str]]
) -> None:
    """R1: every llm_transform step is followed by a validation step before any consumer."""
    by_id = {s.id: s for s in steps}
    direct_dependents: Dict[str, Set[str]] = defaultdict(set)
    for step in steps:
        for dep in step.depends_on or []:
            direct_dependents[dep].add(step.id)
    for transform in steps:
        if transform.step_class != "llm_transform":
            continue
        dependents = [by_id[sid] for sid in direct_dependents.get(transform.id, ())]
        validators = {d.id for d in dependents if d.step_class == "validation"}
        if not validators:
            raise PlanAdmissionError(
                rule="R1",
                reason=(
                    f"llm_transform step '{transform.id}' is not followed by a "
                    "validation step before its output is consumed"
                ),
            )
        for consumer in dependents:
            if consumer.step_class == "validation":
                continue
            if not (validators & transitive_deps[consumer.id]):
                raise PlanAdmissionError(
                    rule="R1",
                    reason=(
                        f"step '{consumer.id}' consumes llm_transform step "
                        f"'{transform.id}' without a validation step in between"
                    ),
                )


def _check_r2_governed_effects(
    steps: List[PlanStep], transitive_deps: Dict[str, Set[str]]
) -> None:
    """R2: governed-effect steps are preceded by an authority check and followed by a receipt."""
    by_id = {s.id: s for s in steps}
    for effect in steps:
        if effect.step_class != "governed_effect":
            continue
        upstream = transitive_deps[effect.id]
        if not any(by_id[sid].step_class == "authority_check" for sid in upstream):
            raise PlanAdmissionError(
                rule="R2",
                reason=(
                    f"governed_effect step '{effect.id}' is not preceded by an "
                    "authority_check step"
                ),
            )
        has_receipt = any(
            step.step_class == "receipt" and effect.id in transitive_deps[step.id]
            for step in steps
        )
        if not has_receipt:
            raise PlanAdmissionError(
                rule="R2",
                reason=(
                    f"governed_effect step '{effect.id}' is not followed by "
                    "receipt emission"
                ),
            )


def _check_r3_leaf_verify_targets(
    steps: List[PlanStep], transitive_deps: Dict[str, Set[str]]
) -> None:
    """R3: plan admissible only if leaf steps have resolvable verify targets."""
    ids = {s.id for s in steps}
    has_dependents: Set[str] = set()
    for step in steps:
        has_dependents.update(step.depends_on or [])
    # Any declared verify target must resolve, leaf or not.
    for step in steps:
        if step.verify is not None:
            _check_verify_target(step, ids, transitive_deps)
    for leaf in steps:
        if leaf.id in has_dependents:
            continue
        target = leaf.verify or _INTRINSIC_VERIFY_BY_KIND.get(leaf.kind)
        if not target:
            raise PlanAdmissionError(
                rule="R3",
                reason=f"leaf step '{leaf.id}' has no resolvable verify target",
            )


def _check_verify_target(
    step: PlanStep, ids: Set[str], transitive_deps: Dict[str, Set[str]]
) -> None:
    raw = (step.verify or "").strip()
    scheme, _, target = raw.partition(":")
    if not raw or not target.strip() or scheme not in VERIFY_TARGET_SCHEMES:
        raise PlanAdmissionError(
            rule="R3",
            reason=(
                f"step '{step.id}' declares unresolvable verify target {step.verify!r} "
                f"(expected '<scheme>:<target>' with scheme in {sorted(VERIFY_TARGET_SCHEMES)})"
            ),
        )
    if scheme == "step":
        verifier = target.strip()
        if verifier not in ids:
            raise PlanAdmissionError(
                rule="R3",
                reason=f"step '{step.id}' names unknown verify step '{verifier}'",
            )
        if step.id not in transitive_deps.get(verifier, set()):
            raise PlanAdmissionError(
                rule="R3",
                reason=(
                    f"verify step '{verifier}' does not depend on step '{step.id}' "
                    "and cannot observe its output"
                ),
            )


def _check_r4_budgets(
    plan: Plan, steps: List[PlanStep], plan_timeout_seconds: float | None
) -> None:
    """R4: per-step budget sum bounded by the plan budget; wall-clock bound must exist."""
    declared = [(s.id, float(s.budget)) for s in steps if s.budget is not None]
    if plan.budget is not None:
        total = sum(budget for _, budget in declared)
        if total > float(plan.budget):
            raise PlanAdmissionError(
                rule="R4",
                reason=(
                    f"per-step budget sum {total} exceeds plan budget {plan.budget}"
                ),
            )
    elif declared:
        raise PlanAdmissionError(
            rule="R4",
            reason=(
                "steps declare budgets "
                f"({', '.join(sid for sid, _ in declared)}) but the plan declares "
                "no plan-level budget to bound them"
            ),
        )
    if plan_timeout_seconds is None or plan_timeout_seconds <= 0:
        raise PlanAdmissionError(
            rule="R4",
            reason="plan-level wall-clock timeout missing or non-positive",
        )


__all__ = [
    "DEFAULT_PLAN_TIMEOUT_SECONDS",
    "PLAN_SCHEMA_REF",
    "PlanAdmissionError",
    "VERIFY_TARGET_SCHEMES",
    "admit_plan",
    "resolve_plan_timeout",
]
