from __future__ import annotations

import pytest

from app.planner.provider import MockPlanner, PlannerInput
from app.planner.tools import get_tool_descriptor

pytestmark = pytest.mark.not_pg


def test_mock_planner_returns_deterministic_steps() -> None:
    planner = MockPlanner()
    inp = PlannerInput(object_uuid="obj-123", goal="demo goal", text="hello world")
    plan = planner.plan(inp)
    assert plan.meta.source_object_uuid == "obj-123"
    assert [(step.id, step.kind, step.step_class) for step in plan.steps] == [
        ("step-1", "agent_call", None),
        ("step-2-authority", "decision", "authority_check"),
        ("step-2", "tool_call", "governed_effect"),
        ("step-2-receipt", "note", "receipt"),
        ("step-3", "decision", None),
    ]

    authority, append, receipt = plan.steps[1:4]
    assert authority.tool == append.tool == "mcp.vault.append_note"
    assert authority.tool_args == append.tool_args
    assert authority.metadata == {"append_effect_step_id": append.id}
    assert append.metadata == {"authority_check_step_id": authority.id}
    assert append.depends_on == [authority.id]
    assert receipt.depends_on == [append.id]
    assert receipt.metadata == {"receipt_from_step": append.id}
    assert receipt.verify == "result:execution_result"
    assert get_tool_descriptor(append.tool) is not None
