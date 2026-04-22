from __future__ import annotations

import time

from app.orchestrator.runtime import Orchestrator
from app.planner.schema import Plan, PlanMetadata, PlanStep


def _plan_with_two_steps() -> Plan:
    return Plan(
        id="plan-timeout-v1",
        meta=PlanMetadata(goal="timeout", source_object_uuid="obj-1", created_by="test", trace_id="trace-1"),
        steps=[
            PlanStep(id="step-1", kind="agent_call", description="sleep", agent="agent"),
            PlanStep(id="step-2", kind="agent_call", description="next", agent="agent"),
        ],
        context={},
    )


class _SlowThenFastExecutor:
    def execute_step(self, step, context):
        if step.id == "step-1":
            time.sleep(0.05)
        return {"ok": step.id}


def test_v1_plan_timeout_budget_stops_plan_without_changing_tool_timeout() -> None:
    orchestrator = Orchestrator(
        executor=_SlowThenFastExecutor(),
        tool_settings={"plan_timeout_seconds": 0.01, "tool_timeout_seconds": 99},
    )
    results = orchestrator.run_plan(_plan_with_two_steps())
    assert len(results) == 2
    assert results[0]["status"] == "ok"
    assert results[1]["status"] == "error"
    assert results[1].get("error_type") == "plan_timeout"


def test_missing_plan_budget_preserves_existing_behavior() -> None:
    orchestrator = Orchestrator(executor=_SlowThenFastExecutor(), tool_settings={"tool_timeout_seconds": 99})
    results = orchestrator.run_plan(_plan_with_two_steps())
    assert [r["status"] for r in results] == ["ok", "ok"]
