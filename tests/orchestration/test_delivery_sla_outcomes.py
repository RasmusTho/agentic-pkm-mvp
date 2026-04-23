from __future__ import annotations

import time

from app.orchestrator.delivery_sla import (
    DELIVERY_SLA_DELIVERED,
    DELIVERY_SLA_FAILED,
    DELIVERY_SLA_ROLLED_BACK,
    DELIVERY_SLA_TIMEOUT,
    map_delivery_sla_terminal_state,
)
from app.orchestrator.runtime import Orchestrator
from app.planner.schema import Plan, PlanMetadata, PlanStep


def _plan() -> Plan:
    return Plan(
        id="plan-delivery-sla",
        meta=PlanMetadata(goal="sla", source_object_uuid="obj-sla", created_by="test", trace_id="trace-sla"),
        steps=[
            PlanStep(id="step-1", kind="agent_call", description="slow", agent="agent"),
            PlanStep(id="step-2", kind="agent_call", description="next", agent="agent"),
        ],
        context={},
    )


class _SlowExecutor:
    def execute_step(self, step, context):
        if step.id == "step-1":
            time.sleep(0.05)
        return {"ok": step.id}


def test_delivery_sla_terminal_state_mapping() -> None:
    assert map_delivery_sla_terminal_state(status="ok") == DELIVERY_SLA_DELIVERED
    assert map_delivery_sla_terminal_state(status="rolled_back") == DELIVERY_SLA_ROLLED_BACK
    assert map_delivery_sla_terminal_state(status="error", error_type="tool_timeout") == DELIVERY_SLA_TIMEOUT
    assert map_delivery_sla_terminal_state(status="error", error_type="plan_timeout") == DELIVERY_SLA_TIMEOUT
    assert map_delivery_sla_terminal_state(status="error", error_type="budget_exhausted") == DELIVERY_SLA_FAILED

    orchestrator = Orchestrator(
        executor=_SlowExecutor(),
        tool_settings={"plan_timeout_seconds": 0.01, "tool_timeout_seconds": 99},
    )
    results = orchestrator.run_plan(_plan())

    assert results[0]["delivery_sla_state"] == DELIVERY_SLA_DELIVERED
    assert results[1]["error_type"] == "plan_timeout"
    assert results[1]["delivery_sla_state"] == DELIVERY_SLA_TIMEOUT
