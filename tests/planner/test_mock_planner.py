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
    assert len(plan.steps) == 3
    tool_steps = [step for step in plan.steps if step.kind == "tool_call"]
    assert tool_steps
    assert tool_steps[0].tool
    assert get_tool_descriptor(tool_steps[0].tool) is not None
