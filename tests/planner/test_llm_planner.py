from __future__ import annotations

import json
from typing import Dict, List

import pytest

from app.agents.base.audit import _audit_ring_snapshot
from app.events.types import PLANNER_PLAN_FALLBACK
from app.planner.provider import LLMPlanner, PlannerInput, select_flow_pattern_prompt

pytestmark = pytest.mark.not_pg


def _fake_plan_payload() -> Dict[str, object]:
    return {
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


def test_select_flow_pattern_prompt_picks_first_entries() -> None:
    flow_profiles = [
        {
            "flow_id": "ingest",
            "suggested_patterns": [{"name": "standard"}, {"name": "extra"}],
            "prompt_profiles": [{"id": "primary"}, {"id": "alt"}],
        },
        {"flow_id": "qa"},
    ]
    selection = select_flow_pattern_prompt(flow_profiles)
    assert selection is not None
    assert selection["flow_id"] == "ingest"
    assert selection["pattern"]["name"] == "standard"
    assert selection["prompt_profile"]["id"] == "primary"
    assert select_flow_pattern_prompt([]) is None


def test_llm_planner_parses_valid_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    planner = LLMPlanner()

    def fake_call_llm(name: str, pack: dict) -> str:
        return json.dumps(_fake_plan_payload())

    monkeypatch.setattr("app.planner.provider.call_llm", fake_call_llm)
    inp = PlannerInput(object_uuid="obj-9", goal="Goal", text="Text body")
    plan = planner.plan(inp)
    assert plan.id == "plan-llm"
    assert plan.meta.source_object_uuid == "obj-9"
    assert plan.meta.created_by == "planner.llm"
    assert len(plan.steps) == 2
    assert "profile_selection" not in plan.context


def test_llm_planner_includes_flow_profile_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    planner = LLMPlanner()
    captured: Dict[str, str] = {}

    def fake_call_llm(name: str, pack: dict) -> str:
        captured["user"] = pack["user"]
        return json.dumps(_fake_plan_payload())

    monkeypatch.setattr("app.planner.provider.call_llm", fake_call_llm)
    flow_profiles = [
        {
            "flow_id": "ingest",
            "intent": "Turn new text into knowledge.",
            "planner_mode": {"strictness": "advisory", "max_steps": 6},
            "suggested_patterns": [{"name": "standard", "steps": [{"target": "agent:normalizer"}]}],
            "prompt_profiles": [{"id": "ingest-default", "prompt_template_ref": "prompts/planner/ingest-default.md"}],
        }
    ]
    inp = PlannerInput(
        object_uuid="obj-501",
        goal="Goal",
        text="Body",
        context={"flow_profiles": flow_profiles, "planning_mode": "profiles"},
        tags=["flow:ingest"],
    )
    plan = planner.plan(inp)
    assert "Flow guidance" in captured["user"]
    assert "ingest" in captured["user"]
    selection = plan.context.get("profile_selection")
    assert selection and selection["flow_id"] == "ingest"
    assert selection["prompt_profile"]["id"] == "ingest-default"


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


def test_llm_planner_legacy_prompt_without_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    planner = LLMPlanner()
    captured: Dict[str, str] = {}

    def fake_call_llm(name: str, pack: dict) -> str:
        captured["user"] = pack["user"]
        return json.dumps(_fake_plan_payload())

    monkeypatch.setattr("app.planner.provider.call_llm", fake_call_llm)
    inp = PlannerInput(object_uuid="obj-300", goal="Goal", text="legacy text")
    plan = planner.plan(inp)
    assert "Flow guidance" not in captured["user"]
    assert "profile_selection" not in plan.context
