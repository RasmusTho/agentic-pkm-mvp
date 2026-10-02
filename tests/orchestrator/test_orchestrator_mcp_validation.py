from __future__ import annotations

import pytest

from app.agents.base.audit import _audit_ring_snapshot
from app.events.types import ORCHESTRATOR_STEP_ERROR
from app.orchestrator.runtime import Orchestrator
from app.planner.provider import build_vault_append_steps
from app.planner.schema import Plan, PlanMetadata

pytestmark = pytest.mark.not_pg


def test_orchestrator_validates_mcp_arguments() -> None:
    plan = Plan(
        id="plan-mcp-invalid",
        meta=PlanMetadata(goal="demo", source_object_uuid="obj-200", created_by="tester"),
        steps=build_vault_append_steps(
            step_id="step-tool",
            description="Attempt to append without full args",
            tool_args={"title": "Missing body"},
            reason="Reach tool argument validation with the required R2 chain",
        ),
    )
    orchestrator = Orchestrator()
    before = _audit_ring_snapshot()
    results = orchestrator.run_plan(plan)
    after = _audit_ring_snapshot()
    assert results[1]["status"] == "error"
    assert "missing required argument" in results[1]["error"]
    assert results[1]["error_type"] == "invalid_tool_args"
    new_events = [evt for evt in after if evt not in before]
    assert any(evt["event_type"] == ORCHESTRATOR_STEP_ERROR for evt in new_events)
