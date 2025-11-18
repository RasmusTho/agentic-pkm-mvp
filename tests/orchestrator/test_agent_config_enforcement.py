from __future__ import annotations

import pytest

from app.orchestrator.runtime import Orchestrator
from app.planner.schema import Plan, PlanMetadata, PlanStep, PlanTrigger
from app.settings.agents import AgentConfig

PLAN_ID = "plan-agent-config"


def _plan(agent: str = "ingest-agent", flow_id: str | None = "ingest", event_type: str = "ingest.object.created") -> Plan:
    step = PlanStep(id="step-1", kind="agent_call", description="Call agent", agent=agent)
    context = {}
    if flow_id:
        context["flow_ids"] = [flow_id]
    return Plan(
        id=PLAN_ID,
        meta=PlanMetadata(goal="Goal", source_object_uuid="obj-1", created_by="tester"),
        steps=[step],
        trigger=PlanTrigger(event_type=event_type, event_id="evt-1"),
        context=context,
    )


def _config(**overrides) -> AgentConfig:
    data = {
        "agent_id": "ingest-agent",
        "agent_type": "planner",
        "enabled": True,
        "flows": ["ingest"],
        "allowed_events": ["ingest.object.created"],
    }
    data.update(overrides)
    return AgentConfig(**data)


def test_agent_executes_when_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config()
    monkeypatch.setattr("app.orchestrator.agents.load_agent_configs", lambda: {cfg.agent_id: cfg})
    plan = _plan()
    results = Orchestrator().run_plan(plan)
    assert results[0]["status"] == "ok"


def test_agent_disabled_causes_permission_error(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config(enabled=False)
    monkeypatch.setattr("app.orchestrator.agents.load_agent_configs", lambda: {cfg.agent_id: cfg})
    plan = _plan()
    results = Orchestrator().run_plan(plan)
    assert results[0]["status"] == "error"
    assert "permission" in results[0]["error"].lower()


def test_agent_flow_mismatch_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config(flows=["qa"])
    monkeypatch.setattr("app.orchestrator.agents.load_agent_configs", lambda: {cfg.agent_id: cfg})
    plan = _plan(flow_id="ingest")
    results = Orchestrator().run_plan(plan)
    assert results[0]["status"] == "error"
    assert "flow" in results[0]["error"].lower()


def test_agent_without_config_runs_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.orchestrator.agents.load_agent_configs", lambda: {})
    plan = _plan(agent="unknown-agent")
    results = Orchestrator().run_plan(plan)
    assert results[0]["status"] == "ok"


def test_agent_flow_legacy_flows_context(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config(flows=["ingest"])
    monkeypatch.setattr("app.orchestrator.agents.load_agent_configs", lambda: {cfg.agent_id: cfg})
    plan = _plan(flow_id=None)
    plan.context = {"flows": ["ingest"]}
    results = Orchestrator().run_plan(plan)
    assert results[0]["status"] == "ok"
