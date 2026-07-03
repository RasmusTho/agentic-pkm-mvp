"""Plan admission validation (KERNEL-09, #2771).

Every test drives the production entrypoint ``OrchestratorV2.run_plan`` (the
real run loop) — admission is asserted as the contract all plans pass through
*before scheduling*, not as an internal helper convention.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest

import app.orchestrator.admission as admission_module
from app.components.llm.constrained import registered_schema
from app.orchestrator.admission import (
    PLAN_SCHEMA_REF,
    PlanAdmissionError,
    admit_planner_payload,
)
from app.orchestrator.v2_runtime import OrchestratorV2
from app.planner.provider import LLMPlanner, PlannerInput
from app.planner.schema import Plan, PlanMetadata, PlanStep

pytestmark = pytest.mark.not_pg


class _RecordingExecutor:
    """Deterministic executor recording which steps were scheduled."""

    def __init__(self, *, sleep_by_step: Dict[str, float] | None = None) -> None:
        self.executed: List[str] = []
        self._sleep_by_step = sleep_by_step or {}

    def execute_step(self, step: PlanStep, context: Any) -> Dict[str, Any]:
        self.executed.append(step.id)
        delay = self._sleep_by_step.get(step.id)
        if delay:
            time.sleep(delay)
        return {"note": step.id}


def _step(
    step_id: str,
    *,
    depends_on: List[str] | None = None,
    step_class: str | None = None,
    verify: str | None = None,
    budget: float | None = None,
) -> PlanStep:
    return PlanStep(
        id=step_id,
        kind="note",
        description=f"step {step_id}",
        depends_on=depends_on or [],
        step_class=step_class,
        verify=verify,
        budget=budget,
    )


def _plan(steps: List[PlanStep], *, budget: float | None = None) -> Plan:
    return Plan(
        id="plan-admission-test",
        meta=PlanMetadata(goal="admission", source_object_uuid="obj-adm", created_by="test"),
        steps=steps,
        budget=budget,
    )


def _assert_rejected_before_scheduling(plan: Plan, rule: str) -> None:
    executor = _RecordingExecutor()
    orchestrator = OrchestratorV2(executor=executor, max_workers=1)
    with pytest.raises(PlanAdmissionError) as excinfo:
        orchestrator.run_plan(plan)
    assert excinfo.value.rule == rule
    assert executor.executed == []  # rejected before any step was scheduled


def test_admission_rejects_r1_r2_r3_r5_violations() -> None:
    # R1: llm_transform output consumed with no validation step in between.
    _assert_rejected_before_scheduling(
        _plan(
            [
                _step("transform", step_class="llm_transform"),
                _step("consumer", depends_on=["transform"]),
            ]
        ),
        "R1",
    )
    # R1: llm_transform with no validation step at all.
    _assert_rejected_before_scheduling(
        _plan([_step("transform", step_class="llm_transform")]),
        "R1",
    )
    # R2: governed effect without an authority check before it.
    _assert_rejected_before_scheduling(
        _plan(
            [
                _step("effect", step_class="governed_effect"),
                _step("receipt", depends_on=["effect"], step_class="receipt"),
            ]
        ),
        "R2",
    )
    # R2: governed effect without receipt emission after it.
    _assert_rejected_before_scheduling(
        _plan(
            [
                _step("authority", step_class="authority_check"),
                _step("effect", depends_on=["authority"], step_class="governed_effect"),
            ]
        ),
        "R2",
    )
    # R3: leaf step with an unresolvable verify target.
    _assert_rejected_before_scheduling(
        _plan([_step("leaf", verify="vibes")]),
        "R3",
    )
    # R3: verify names a step that cannot observe the verified step's output.
    _assert_rejected_before_scheduling(
        _plan(
            [
                _step("first", verify="step:leaf"),
                _step("leaf", depends_on=["first"], verify="step:first"),
            ]
        ),
        "R3",
    )
    # R5: dependency cycle.
    _assert_rejected_before_scheduling(
        _plan(
            [
                _step("a", depends_on=["b"]),
                _step("b", depends_on=["a"]),
            ]
        ),
        "R5",
    )
    # R5: unknown dependency reference (legacy _validate_step passed on these).
    _assert_rejected_before_scheduling(
        _plan([_step("a", depends_on=["ghost"])]),
        "R5",
    )

    # A conforming plan exercising every rule is admitted and fully scheduled.
    conforming = _plan(
        [
            _step("authority", step_class="authority_check", budget=1),
            _step("transform", depends_on=["authority"], step_class="llm_transform", budget=1),
            _step("validate", depends_on=["transform"], step_class="validation", budget=1),
            _step("effect", depends_on=["validate"], step_class="governed_effect", budget=1),
            _step("receipt", depends_on=["effect"], step_class="receipt", budget=1),
        ],
        budget=10,
    )
    executor = _RecordingExecutor()
    results = OrchestratorV2(executor=executor, max_workers=1).run_plan(conforming)
    assert [entry["status"] for entry in results] == ["ok"] * 5
    assert len(executor.executed) == 5


def test_budget_sum_bounded() -> None:
    # Per-step budget sum exceeding the plan budget is inadmissible.
    _assert_rejected_before_scheduling(
        _plan(
            [_step("a", budget=3), _step("b", depends_on=["a"], budget=3)],
            budget=5,
        ),
        "R4",
    )
    # Per-step budgets without any plan-level bound are inadmissible (fail-loud,
    # never silently unbounded).
    _assert_rejected_before_scheduling(
        _plan([_step("a", budget=1)]),
        "R4",
    )
    # A bounded plan is admitted and runs.
    executor = _RecordingExecutor()
    results = OrchestratorV2(executor=executor, max_workers=1).run_plan(
        _plan(
            [_step("a", budget=2), _step("b", depends_on=["a"], budget=2)],
            budget=5,
        )
    )
    assert [entry["status"] for entry in results] == ["ok", "ok"]


def test_plan_timeout_enforced_from_run_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    # No opt-in anywhere: no orchestrator tool_settings, no plan-context
    # tool_settings, no plan_timeout_seconds. Only the mandatory default is
    # shrunk so the test can observe it firing.
    monkeypatch.setattr(admission_module, "DEFAULT_PLAN_TIMEOUT_SECONDS", 0.01)

    executor = _RecordingExecutor(sleep_by_step={"slow": 0.05})
    orchestrator = OrchestratorV2(executor=executor, max_workers=1)
    plan = _plan([_step("slow"), _step("after", depends_on=["slow"])])

    results = orchestrator.run_plan(plan)

    timeout_entries = [r for r in results if r.get("error_type") == "plan_timeout"]
    assert timeout_entries, f"expected plan_timeout entry, got {results}"
    assert timeout_entries[0]["step_id"] == "after"
    assert "after" not in executor.executed  # the plan halted; no step ran past the wall-clock


def test_plan_schema_validated_at_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    # The plan schema is a named KERNEL-07 registry artifact.
    schema = registered_schema(PLAN_SCHEMA_REF)
    assert "steps" in schema.get("properties", {})

    # run_plan routes every admitted plan through the KERNEL-07 validator.
    validated_refs: List[str] = []
    real_validate = admission_module.validate_payload

    def _spy(schema_ref: str, payload: Any) -> Any:
        validated_refs.append(schema_ref)
        return real_validate(schema_ref, payload)

    monkeypatch.setattr(admission_module, "validate_payload", _spy)
    OrchestratorV2(executor=_RecordingExecutor(), max_workers=1).run_plan(_plan([_step("s1")]))
    assert PLAN_SCHEMA_REF in validated_refs

    # Malformed planner JSON is rejected at admission with a typed failure.
    with pytest.raises(PlanAdmissionError) as excinfo:
        admit_planner_payload({"id": "plan-x", "steps": "not-a-list"})
    assert excinfo.value.rule == "schema"

    # Production planner call site: LLMPlanner output goes through
    # constrained_completion — prose-wrapped or shape-drifted JSON never
    # becomes a plan by prompt convention; it routes to the audited fallback.
    class _ProseClient:
        def chat(self, *args: Any, **kwargs: Any) -> str:
            return 'Sure! Here is your plan: {"id": "plan-x"}'

    monkeypatch.setattr("app.planner.provider.get_chat_client", lambda intent: _ProseClient())
    fallback = LLMPlanner().plan(PlannerInput(object_uuid="obj-adm", goal="g", text="t"))
    assert fallback.meta.created_by == "planner.mock"

    class _ShapeDriftClient:
        def chat(self, *args: Any, **kwargs: Any) -> str:
            return '{"id": "plan-x"}'  # valid JSON, violates the registered schema (no meta)

    monkeypatch.setattr(
        "app.planner.provider.get_chat_client", lambda intent: _ShapeDriftClient()
    )
    fallback = LLMPlanner().plan(PlannerInput(object_uuid="obj-adm", goal="g", text="t"))
    assert fallback.meta.created_by == "planner.mock"
