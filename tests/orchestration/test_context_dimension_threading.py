from __future__ import annotations

from app.orchestrator.runtime import Orchestrator
from app.planner.schema import Plan, PlanMetadata, PlanStep


class _CaptureExecutor:
    def __init__(self) -> None:
        self.contexts = []

    def execute_step(self, step, context):
        self.contexts.append(context)
        return {"ok": True}


def test_context_dimensions_in_step_context() -> None:
    executor = _CaptureExecutor()
    orchestrator = Orchestrator(executor=executor)
    plan = Plan(
        id="plan-ctx-dims",
        meta=PlanMetadata(goal="ctx", source_object_uuid="obj-1", created_by="test", trace_id="trace-1"),
        steps=[PlanStep(id="step-1", kind="note", description="noop")],
        context={
            "scope": "work",
            "sphere_memberships": ["team", "learning"],
            "situated_identity": "maker",
        },
    )

    results = orchestrator.run_plan(plan)

    assert results[0]["status"] == "ok"
    assert len(executor.contexts) == 1
    ctx = executor.contexts[0]
    assert ctx.scope == "work"
    assert ctx.sphere_memberships == ["team", "learning"]
    assert ctx.situated_identity == "maker"
