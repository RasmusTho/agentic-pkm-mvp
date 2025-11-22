from __future__ import annotations

from app.events.models import new_event
from app.planner import events as planner_events
from app.planner.schema import Plan, PlanMetadata, PlanStep


class _StubPlanner:
    def __init__(self, steps):
        self.steps = steps

    def plan(self, inp):
        return Plan(
            id="plan-1",
            meta=PlanMetadata(goal=inp.goal, source_object_uuid=inp.object_uuid, created_by="stub"),
            steps=list(self.steps),
            goal=inp.goal,
            context=dict(inp.context),
            tags=list(inp.tags),
        )


class _DummyStore:
    def __init__(self):
        self.saved = None

    def save(self, plan):
        self.saved = plan


def _note_event():
    return new_event(event_type="ingest.object.updated", payload={"object_uuid": "abc", "text": "Body"})


def test_plan_filters_move_steps_when_disabled(monkeypatch):
    move_step = PlanStep(
        id="step-1",
        kind="tool_call",
        description="Move note to Archive",
        tool="mcp.vault.move_note",
    )
    keep_step = PlanStep(id="step-2", kind="agent_call", description="Process note", agent="ingest-agent")
    stub_planner = _StubPlanner([move_step, keep_step])
    store = _DummyStore()

    monkeypatch.setattr(planner_events, "get_planner", lambda: stub_planner)
    monkeypatch.setattr(planner_events, "get_plan_store", lambda: store)
    monkeypatch.setattr(planner_events, "get_flow_profiles_for_event", lambda event_type, profile_map=None: [])
    monkeypatch.setattr(planner_events, "get_legacy_flows_for_event", lambda event_type: [])
    monkeypatch.setattr(planner_events, "load_flow_profiles", lambda: {})

    plan = planner_events.plan_for_event(_note_event(), ctx={"note_moves_enable": False})

    assert len(plan.steps) == 2
    assert plan.steps[0].kind == "note"
    assert plan.steps[0].metadata.get("skipped_move") is True
    assert plan.steps[0].metadata.get("note_moves_enable") is False
    assert "Skip move" in plan.steps[0].description
    assert plan.steps[1].kind == "agent_call"


def test_plan_keeps_move_steps_when_enabled(monkeypatch):
    move_step = PlanStep(
        id="step-1",
        kind="tool_call",
        description="Move note to Archive",
        tool="mcp.vault.move_note",
    )
    stub_planner = _StubPlanner([move_step])
    store = _DummyStore()

    monkeypatch.setattr(planner_events, "get_planner", lambda: stub_planner)
    monkeypatch.setattr(planner_events, "get_plan_store", lambda: store)
    monkeypatch.setattr(planner_events, "get_flow_profiles_for_event", lambda event_type, profile_map=None: [])
    monkeypatch.setattr(planner_events, "get_legacy_flows_for_event", lambda event_type: [])
    monkeypatch.setattr(planner_events, "load_flow_profiles", lambda: {})

    plan = planner_events.plan_for_event(_note_event(), ctx={"note_moves_enable": True})

    assert len(plan.steps) == 1
    assert plan.steps[0].kind == "tool_call"
    assert plan.steps[0].tool == "mcp.vault.move_note"
    assert plan.context.get("note_moves_enable") is True
