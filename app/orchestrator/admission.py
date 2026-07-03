"""Plan admission validation (KERNEL-09, #2771).

Every plan passes through :func:`admit_plan` in ``OrchestratorV2.run_plan``
*before scheduling*. Admission moves plan-shape and boundedness failures from
the most expensive detection point (step execution) to the cheapest one
(admission), per audit invariant I-A4 and the §3 decomposition model of
``docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md``.

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
  by default: ``resolve_plan_timeout`` falls back to
  ``DEFAULT_PLAN_TIMEOUT_SECONDS`` when ``plan_timeout_seconds`` is absent or
  non-positive, so no admitted plan runs unbounded.
- **R5** — the plan is a DAG: unknown/duplicate step references and dependency
  cycles are rejected (the legacy ``_validate_step`` explicitly passed on
  forward references and never detected cycles).

``step_class`` declarations are opt-in on the existing ``PlanStep`` shape
(extend, not fork): legacy plans without declarations are still held to the
structural rules (schema, R3 intrinsic targets, R4 timeout, R5 DAG), while the
ordering rules R1/R2 bind as soon as a plan declares transform or
governed-effect steps.

Failure semantics are explicit and loud: any violation raises
:class:`PlanAdmissionError` naming the rule; there is no silent repair and no
partial admission.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Mapping, Set

from app.components.llm.constrained import ConstrainedCompletionError, validate_payload
from app.planner.plan_schema import PLAN_SCHEMA_REF
from app.planner.schema import Plan, PlanStep

#: Mandatory-by-default plan-level wall-clock budget (seconds). An explicit
#: positive ``plan_timeout_seconds`` in tool settings overrides it; absence or
#: a non-positive value falls back here — never to "unbounded".
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


def resolve_plan_timeout(tool_settings: Mapping[str, Any] | None) -> float:
    """Return the effective plan-level wall-clock timeout in seconds.

    An explicit positive ``plan_timeout_seconds`` wins; anything else (absent,
    unparsable, zero, negative) resolves to ``DEFAULT_PLAN_TIMEOUT_SECONDS``.
    The return value is always positive: a plan without a wall-clock bound is
    not a state this function can produce.
    """
    raw = tool_settings.get("plan_timeout_seconds") if tool_settings else None
    try:
        supplied = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        supplied = None
    if supplied is not None and supplied > 0:
        return supplied
    return DEFAULT_PLAN_TIMEOUT_SECONDS


def admit_planner_payload(payload: Any) -> Plan:
    """Admit raw planner JSON: KERNEL-07 schema validation, then model parse.

    This is the entry for payloads that have not yet become ``Plan`` objects;
    schema violations raise :class:`PlanAdmissionError` (rule ``schema``)
    before any pydantic coercion can paper over shape drift.
    """
    try:
        validate_payload(PLAN_SCHEMA_REF, payload)
    except ConstrainedCompletionError as exc:
        raise PlanAdmissionError(rule="schema", reason=exc.reason) from exc
    return Plan.model_validate(payload)


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
    "admit_planner_payload",
    "resolve_plan_timeout",
]
