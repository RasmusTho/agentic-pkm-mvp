from __future__ import annotations

import pytest

from app.events.models import new_event
from app.events.types import ASK_QUERY_RECEIVED, INGEST_OBJECT_CREATED
from app.planner.events import plan_for_event, planner_profiles_enabled
from app.settings.flow_profiles import FlowProfile, PromptProfile, SuggestedPattern
from app.stores.plan_store import get_plan_store, reset_plan_store


def setup_function() -> None:
    reset_plan_store()


def test_ingest_event_produces_plan_with_flow_tags() -> None:
    event = new_event(
        event_type=INGEST_OBJECT_CREATED,
        payload={
            "uuid": "obj-100",
            "content": "Body",
            "title": "Demo",
        },
    )
    plan = plan_for_event(event, ctx={"origin": "test"})
    assert plan.trigger is not None
    assert plan.trigger.event_type == INGEST_OBJECT_CREATED
    assert plan.trigger.event_id == event.event_id
    assert any(tag in {"ingest", "flow:ingest"} for tag in plan.tags)
    assert plan.goal
    stored = get_plan_store().get(plan.id)
    assert stored is plan


def test_ask_event_maps_to_qa_flow() -> None:
    event = new_event(event_type=ASK_QUERY_RECEIVED, payload={"question": "How to plan?"})
    plan = plan_for_event(event)
    assert plan.trigger is not None
    assert plan.trigger.event_type == ASK_QUERY_RECEIVED
    assert any(tag in {"qa", "flow:qa"} for tag in plan.tags)


def test_planner_profiles_flag_prefers_ctx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLANNER_PROFILES_ENABLE", raising=False)
    assert planner_profiles_enabled(None) is False
    monkeypatch.setenv("PLANNER_PROFILES_ENABLE", "1")
    assert planner_profiles_enabled(None) is True
    assert planner_profiles_enabled({"planner_profiles_enable": "0"}) is False
    assert planner_profiles_enabled({"planner_profiles_enable": "yes"}) is True


def test_plan_for_event_uses_flow_profiles_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLANNER_PROFILES_ENABLE", "1")
    profile = FlowProfile(
        flow_id="ingest",
        name="Ingest profile",
        event_triggers=[INGEST_OBJECT_CREATED],
        intent="Turn new text into knowledge.",
        suggested_patterns=[
            SuggestedPattern(name="standard", description="Standard", steps=["agent:normalizer", "mcp:vault.append_note"])
        ],
        prompt_profiles=[
            PromptProfile(id="ingest-default", prompt_template_ref="prompts/planner/ingest-default.md")
        ],
    )
    monkeypatch.setattr("app.planner.events.load_flow_profiles", lambda: {profile.flow_id: profile})
    event = new_event(event_type=INGEST_OBJECT_CREATED, payload={"uuid": "obj-501", "content": "Body"})
    plan = plan_for_event(event)
    assert plan.context.get("planning_mode") == "profiles"
    assert plan.context.get("flow_profiles")
    assert plan.context["flow_profiles"][0]["intent"] == "Turn new text into knowledge."
    assert "flow:ingest" in plan.tags
    assert len(plan.steps) == 2
    assert plan.steps[0].kind == "agent_call"
    assert plan.steps[0].agent == "normalizer"
    assert plan.steps[1].kind == "tool_call"
    assert plan.steps[1].tool == "mcp.vault.append_note"
    selection = plan.context.get("profile_selection")
    assert selection and selection["flow_id"] == "ingest"
    assert selection["pattern"]["name"] == "standard"
    assert selection["prompt_profile"]["id"] == "ingest-default"


def test_plan_for_event_profiles_enabled_without_matches_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLANNER_PROFILES_ENABLE", "1")
    empty_profile = FlowProfile(flow_id="qa", event_triggers=[ASK_QUERY_RECEIVED])
    monkeypatch.setattr("app.planner.events.load_flow_profiles", lambda: {empty_profile.flow_id: empty_profile})
    event = new_event(event_type=INGEST_OBJECT_CREATED, payload={"uuid": "obj-999"})
    plan = plan_for_event(event)
    assert plan.context.get("planning_mode") != "profiles"
    assert "flow:ingest" in plan.tags
    assert not plan.context.get("flow_profiles")
