from __future__ import annotations

import json

import pytest

from app.agents.base.audit import _audit_ring_snapshot
from app.events.types import PLANNER_PLAN_FALLBACK
from app.planner.provider import LLMPlanner, PlannerInput

pytestmark = pytest.mark.not_pg


def test_llm_planner_parses_valid_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    planner = LLMPlanner()

    def fake_call_llm(name: str, pack: dict) -> str:
        return json.dumps(
            {
                "id": "plan-llm",
                "meta": {
                    "goal": "Plan goal",
                    "source_object_uuid": "obj-9",
                    "created_by": "planner.llm",
                    "trace_id": "trace-1",
                },
                "steps": [
                    {"id": "s1", "kind": "agent_call", "description": "Do work"},
                    {"id": "s2", "kind": "tool_call", "description": "Use tool", "tool": "mcp.search.objects"},
                ],
            }
        )

    monkeypatch.setattr("app.planner.provider.call_llm", fake_call_llm)
    inp = PlannerInput(object_uuid="obj-9", goal="Goal", text="Text body")
    plan = planner.plan(inp)
    assert plan.id == "plan-llm"
    assert plan.meta.source_object_uuid == "obj-9"
    assert plan.meta.created_by == "planner.llm"
    assert len(plan.steps) == 2


def test_llm_planner_falls_back_on_invalid_output(monkeypatch: pytest.MonkeyPatch) -> None:
    planner = LLMPlanner()
    monkeypatch.setattr("app.planner.provider.call_llm", lambda name, pack: "not-json")
    inp = PlannerInput(object_uuid="obj-10", goal="Goal", text="body", metadata={"trace_id": "trace-x"})
    before = _audit_ring_snapshot()
    plan = planner.plan(inp)
    after = _audit_ring_snapshot()
    assert plan.meta.created_by == "planner.mock"
    new_events = [evt for evt in after if evt not in before]
    assert any(evt["event_type"] == PLANNER_PLAN_FALLBACK for evt in new_events)
