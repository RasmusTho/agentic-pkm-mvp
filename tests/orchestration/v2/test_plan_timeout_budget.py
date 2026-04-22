from __future__ import annotations

import time

from app.orchestrator.v2_runtime import OrchestratorV2
from app.planner.schema import Plan, PlanMetadata, PlanStep


def _plan_with_dependency() -> Plan:
    return Plan(
        id="plan-timeout-v2",
        meta=PlanMetadata(goal="timeout", source_object_uuid="obj-2", created_by="test", trace_id="trace-2"),
        steps=[
            PlanStep(id="step-1", kind="agent_call", description="sleep", agent="agent", metadata={"compensate_fn": "undo_step_1"}),
            PlanStep(id="step-2", kind="agent_call", description="next", agent="agent", depends_on=["step-1"]),
        ],
        context={},
    )


class _V2SlowExecutor:
    def execute_step(self, step, context):
        if step.metadata.get("compensation"):
            return {"compensated": step.metadata.get("original_step_id")}
        if step.id == "step-1":
            time.sleep(0.05)
        return {"ok": step.id}


def test_v2_plan_timeout_budget_uses_distinct_error_type_and_compensates() -> None:
    orchestrator = OrchestratorV2(
        executor=_V2SlowExecutor(),
        tool_settings={"plan_timeout_seconds": 0.01, "tool_timeout_seconds": 99},
        max_workers=1,
    )
    results = orchestrator.run_plan(_plan_with_dependency())

    timeout_entries = [r for r in results if r.get("error_type") == "plan_timeout"]
    assert timeout_entries

    compensation_entries = [r for r in results if r.get("step_id") == "__compensation__"]
    assert compensation_entries
