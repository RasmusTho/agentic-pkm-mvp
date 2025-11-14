from __future__ import annotations

import pytest

from app.agents.base.audit import _audit_ring_snapshot
from app.orchestrator.runtime import Orchestrator
from app.planner.schema import Plan, PlanMetadata, PlanStep

pytestmark = pytest.mark.not_pg


def test_orchestrator_validates_mcp_arguments() -> None:
    plan = Plan(
        id="plan-mcp-invalid",
        meta=PlanMetadata(goal="demo", source_object_uuid="obj-200", created_by="tester"),
        steps=[
            PlanStep(
                id="step-tool",
                kind="tool_call",
                description="Attempt to append without full args",
                tool="mcp.vault.append_note",
                tool_args={"note_id": "bad-only"},
            )
        ],
    )
    orchestrator = Orchestrator()
    before = _audit_ring_snapshot()
    results = orchestrator.run_plan(plan)
    after = _audit_ring_snapshot()
    assert results and results[0]["status"] == "error"
    assert "missing required argument" in results[0]["error"]
    new_events = [evt for evt in after if evt not in before]
    assert any(evt["action"] == "orchestrator.step.error" for evt in new_events)
