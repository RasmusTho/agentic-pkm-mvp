from __future__ import annotations

import pytest

from app.a2a.schema import AgentRequest, AgentResponse, new_response
from app.agents.base.audit import _audit_ring_snapshot
from app.events.types import (
    AGENT_ERROR_CREATED,
    AGENT_REQUEST_CREATED,
    AGENT_RESPONSE_CREATED,
)
from app.orchestrator.executor import MockPlanExecutor
from app.orchestrator.runtime import Orchestrator
from app.planner.schema import Plan, PlanMetadata, PlanStep

pytestmark = pytest.mark.not_pg


def _plan_with_agent(agent: str) -> Plan:
    return Plan(
        id="plan-agent-only",
        meta=PlanMetadata(goal="demo", source_object_uuid="obj-201", created_by="tester"),
        steps=[
            PlanStep(
                id="step-agent",
                kind="agent_call",
                description="Ask reviewer to analyze note",
                agent=agent,
                intent="analyze",
            )
        ],
    )


def _ok_handler(request: AgentRequest) -> AgentResponse:
    return new_response(
        sender="review-agent",
        recipient=request.sender,
        status="ok",
        payload={"result": "analysis complete"},
        correlation_id=request.correlation_id,
        trace_id=request.trace_id,
    )


def test_unsupported_agent_emits_request_and_error() -> None:
    """Unsupported recipient (no handler) emits request event, error event, and step fails."""
    plan = _plan_with_agent("review-agent")
    orchestrator = Orchestrator()
    before = _audit_ring_snapshot()
    results = orchestrator.run_plan(plan)
    after = _audit_ring_snapshot()
    new_events = [evt for evt in after if evt not in before]
    assert any(evt["event_type"] == AGENT_REQUEST_CREATED for evt in new_events)
    assert any(
        evt["event_type"] == AGENT_ERROR_CREATED
        and evt["payload"].get("details", {}).get("error_type") == "not_implemented"
        for evt in new_events
    )
    assert results[0]["status"] == "error"
    assert results[0].get("error_type") == "not_implemented"


def test_supported_agent_routes_through_handler_and_emits_response() -> None:
    """Supported recipient (handler registered) routes through handler, emits response event, step succeeds."""
    plan = _plan_with_agent("review-agent")
    executor = MockPlanExecutor(handlers={"review-agent": _ok_handler})
    orchestrator = Orchestrator(executor=executor)
    before = _audit_ring_snapshot()
    results = orchestrator.run_plan(plan)
    after = _audit_ring_snapshot()
    new_events = [evt for evt in after if evt not in before]
    assert any(evt["event_type"] == AGENT_REQUEST_CREATED for evt in new_events)
    assert any(evt["event_type"] == AGENT_RESPONSE_CREATED for evt in new_events)
    assert not any(evt["event_type"] == AGENT_ERROR_CREATED for evt in new_events)
    assert results[0]["status"] == "ok"
    assert results[0]["result"]["response"]["status"] == "ok"
    assert results[0]["result"]["response"]["payload"]["result"] == "analysis complete"


def test_permission_check_runs_before_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Permission check gates handler dispatch: disabled agent fails before handler runs."""
    from app.settings.agents import AgentConfig

    cfg = AgentConfig(agent_id="review-agent", agent_type="planner", enabled=False)
    monkeypatch.setattr("app.orchestrator.agents.load_agent_configs", lambda: {"review-agent": cfg})
    plan = _plan_with_agent("review-agent")
    executor = MockPlanExecutor(handlers={"review-agent": _ok_handler})
    orchestrator = Orchestrator(executor=executor)
    results = orchestrator.run_plan(plan)
    assert results[0]["status"] == "error"
    assert results[0].get("error_type") == "agent_permission"


def test_handler_exception_emits_error_event_and_fails_step() -> None:
    """Handler raising an exception must emit agent.error.created and surface as a failed step."""
    def _raising_handler(request: AgentRequest) -> AgentResponse:
        raise RuntimeError("handler crashed")

    plan = _plan_with_agent("review-agent")
    executor = MockPlanExecutor(handlers={"review-agent": _raising_handler})
    orchestrator = Orchestrator(executor=executor)
    before = _audit_ring_snapshot()
    results = orchestrator.run_plan(plan)
    after = _audit_ring_snapshot()
    new_events = [evt for evt in after if evt not in before]

    assert results[0]["status"] == "error"
    assert results[0].get("error_type") == "handler_error"
    assert any(evt["event_type"] == AGENT_REQUEST_CREATED for evt in new_events)
    assert any(
        evt["event_type"] == AGENT_ERROR_CREATED
        and evt["payload"].get("details", {}).get("error_type") == "handler_error"
        for evt in new_events
    )
    assert not any(evt["event_type"] == AGENT_RESPONSE_CREATED for evt in new_events)
