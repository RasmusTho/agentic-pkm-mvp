from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.planner.schema import Plan, PlanMetadata, PlanStep, make_simple_plan
from app.planner.tools import get_tool_descriptor

pytestmark = pytest.mark.not_pg


def test_plan_schema_accepts_tool_steps() -> None:
    descriptor = get_tool_descriptor("mcp.vault.append_note")
    assert descriptor is not None
    plan = Plan(
        id="plan-test",
        meta=PlanMetadata(goal="test goal", source_object_uuid="obj-1", created_by="planner.mock"),
        steps=[
            PlanStep(
                id="step-1",
                kind="agent_call",
                description="Review inputs",
                agent="review-agent",
                intent="summarize",
            ),
            PlanStep(
                id="step-2",
                kind="tool_call",
                description="Append note",
                tool=descriptor.name,
                tool_args={"title": "Summary", "body": "summary"},
                depends_on=["step-1"],
            ),
        ],
    )
    assert len(plan.steps) == 2
    assert plan.steps[1].tool == descriptor.name


def test_plan_step_rejects_invalid_kind() -> None:
    with pytest.raises(ValidationError):
        PlanStep(id="step-x", kind="invalid", description="noop")  # type: ignore[arg-type]


def test_make_simple_plan_defaults() -> None:
    plan = make_simple_plan(goal="demo", source_object_uuid="obj-2", created_by="planner.mock")
    assert plan.meta.goal == "demo"
    assert plan.meta.source_object_uuid == "obj-2"
    assert plan.steps
