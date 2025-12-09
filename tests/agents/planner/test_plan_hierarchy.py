from __future__ import annotations

import pytest

from app.domain.plan import Plan, PlanStep

pytestmark = [pytest.mark.not_pg]


def test_subplan_creation_links_parent_and_depth() -> None:
    goal = "Top goal"
    plan = Plan.create_top_level(goal=goal, max_steps=5, max_replans=1)
    step = PlanStep(id="composite-1", kind="composite", goal="Sub goal", args={})
    plan.steps.append(step)

    subplan = plan.create_subplan_for_step(step_id="composite-1", max_steps=3, max_replans=0)

    assert subplan.parent_plan == plan.uuid
    assert subplan.depth == plan.depth + 1
    assert subplan.goal == step.goal
    assert subplan.status == "planned"
    # parent plan remains intact
    assert plan.steps[0] is step
    assert plan.steps[0].kind == "composite"


def test_try_create_subplan_respects_max_depth() -> None:
    plan = Plan.create_top_level(goal="Deeper goal", max_steps=2, max_replans=0)
    # Simulate a plan already at max depth
    plan.depth = 1
    composite_step = PlanStep(id="composite-1", kind="composite", goal="nested goal", args={})
    plan.steps.append(composite_step)

    subplan = plan.try_create_subplan_for_step(
        step_id="composite-1",
        max_depth=plan.depth,  # depth >= max_depth triggers no subplan
        max_steps=1,
        max_replans=0,
    )

    assert subplan is None
    # step is left unchanged in this implementation
    assert composite_step.kind == "composite"
    assert composite_step.state == "pending"
