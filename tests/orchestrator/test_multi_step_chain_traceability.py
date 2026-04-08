"""Multi-step chain traceability: prove trace_id continuity across routed agent_call steps.

Covers:
- V1 sequential orchestrator: multi-step plan with chained agent_call steps
- V2 parallel orchestrator (via create_orchestrator + ORCHESTRATOR_VERSION flag):
  multi-step plan with dependency-aware agent_call steps
- Trace continuity: every audit event (request, response, step started/finished)
  carries the same trace_id across all steps in the plan
- Routing receipt: each agent_call step produces a response with matching
  trace_id and correlation_id

Governing issue: #362
"""

from __future__ import annotations

import pytest

from app.a2a.schema import AgentRequest, AgentResponse, new_response
from app.agents.base.audit import _audit_ring_snapshot
from app.events.types import (
    AGENT_REQUEST_CREATED,
    AGENT_RESPONSE_CREATED,
    ORCHESTRATOR_STEP_FINISHED,
    ORCHESTRATOR_STEP_STARTED,
)
from app.orchestrator.executor import MockPlanExecutor
from app.orchestrator.runtime import Orchestrator, create_orchestrator
from app.planner.schema import Plan, PlanMetadata, PlanStep

pytestmark = pytest.mark.not_pg

TRACE_ID = "trace-multi-step-chain-001"


def _echo_handler(agent_name: str):
    """Return a handler that echoes back trace_id and correlation_id for a given agent."""

    def handler(request: AgentRequest) -> AgentResponse:
        return new_response(
            sender=agent_name,
            recipient=request.sender,
            status="ok",
            payload={"agent": agent_name, "echoed_trace": request.trace_id},
            correlation_id=request.correlation_id,
            trace_id=request.trace_id,
        )

    return handler


def _multi_agent_plan() -> Plan:
    """Three-step plan: two chained agent_call steps + a decision step.

    step-1: agent_call to ingest-agent (no deps)
    step-2: agent_call to review-agent (depends on step-1)
    step-3: decision (depends on step-2)
    """
    return Plan(
        id="plan-chain-trace",
        meta=PlanMetadata(
            goal="Multi-agent chain traceability",
            source_object_uuid="obj-chain-001",
            created_by="test",
            trace_id=TRACE_ID,
        ),
        steps=[
            PlanStep(
                id="step-1",
                kind="agent_call",
                description="Ingest and summarize",
                agent="ingest-agent",
                intent="summarize",
            ),
            PlanStep(
                id="step-2",
                kind="agent_call",
                description="Review the summary",
                agent="review-agent",
                intent="review",
                depends_on=["step-1"],
            ),
            PlanStep(
                id="step-3",
                kind="decision",
                description="Decide follow-up",
                depends_on=["step-2"],
            ),
        ],
    )


def _build_executor() -> MockPlanExecutor:
    return MockPlanExecutor(
        handlers={
            "ingest-agent": _echo_handler("ingest-agent"),
            "review-agent": _echo_handler("review-agent"),
        }
    )


# ---------------------------------------------------------------------------
# V1 sequential orchestrator
# ---------------------------------------------------------------------------


class TestV1MultiStepChainTraceability:
    """V1 orchestrator: sequential multi-step plan preserves trace_id across all events."""

    def test_all_steps_succeed_with_trace_continuity(self) -> None:
        plan = _multi_agent_plan()
        executor = _build_executor()
        orchestrator = Orchestrator(executor=executor)

        before = _audit_ring_snapshot()
        results = orchestrator.run_plan(plan)
        after = _audit_ring_snapshot()

        # All three steps complete successfully
        assert len(results) == 3
        assert all(r["status"] == "ok" for r in results)

        # Both agent_call steps return responses that echo back the trace_id
        for r in results[:2]:
            resp = r["result"]["response"]
            assert resp["trace_id"] == TRACE_ID
            assert resp["payload"]["echoed_trace"] == TRACE_ID

        # Every new audit event carries the plan trace_id
        new_events = [evt for evt in after if evt not in before]
        assert len(new_events) > 0
        for evt in new_events:
            assert evt.get("trace_id") == TRACE_ID, (
                f"Event {evt['event_type']} missing trace_id: {evt}"
            )

    def test_trace_covers_request_and_response_per_agent_step(self) -> None:
        plan = _multi_agent_plan()
        executor = _build_executor()
        orchestrator = Orchestrator(executor=executor)

        before = _audit_ring_snapshot()
        orchestrator.run_plan(plan)
        after = _audit_ring_snapshot()

        new_events = [evt for evt in after if evt not in before]
        requests = [e for e in new_events if e["event_type"] == AGENT_REQUEST_CREATED]
        responses = [e for e in new_events if e["event_type"] == AGENT_RESPONSE_CREATED]

        # Two agent_call steps -> two request events, two response events
        assert len(requests) == 2
        assert len(responses) == 2

        # Each request/response pair shares the same trace_id
        for req in requests:
            assert req["trace_id"] == TRACE_ID
        for resp in responses:
            assert resp["trace_id"] == TRACE_ID

    def test_step_started_finished_events_per_step(self) -> None:
        plan = _multi_agent_plan()
        executor = _build_executor()
        orchestrator = Orchestrator(executor=executor)

        before = _audit_ring_snapshot()
        orchestrator.run_plan(plan)
        after = _audit_ring_snapshot()

        new_events = [evt for evt in after if evt not in before]
        started = [e for e in new_events if e["event_type"] == ORCHESTRATOR_STEP_STARTED]
        finished = [e for e in new_events if e["event_type"] == ORCHESTRATOR_STEP_FINISHED]

        # Three steps -> three started, three finished
        assert len(started) == 3
        assert len(finished) == 3

        for evt in started + finished:
            assert evt["trace_id"] == TRACE_ID

    def test_correlation_id_links_request_to_step(self) -> None:
        """Each agent_call request carries step.id as correlation_id."""
        plan = _multi_agent_plan()
        executor = _build_executor()
        orchestrator = Orchestrator(executor=executor)

        before = _audit_ring_snapshot()
        orchestrator.run_plan(plan)
        after = _audit_ring_snapshot()

        new_events = [evt for evt in after if evt not in before]
        requests = [e for e in new_events if e["event_type"] == AGENT_REQUEST_CREATED]

        correlation_ids = {
            e["payload"]["details"]["correlation_id"] for e in requests
        }
        assert "step-1" in correlation_ids
        assert "step-2" in correlation_ids


# ---------------------------------------------------------------------------
# V2 parallel orchestrator (flagged path)
# ---------------------------------------------------------------------------


class TestV2MultiStepChainTraceability:
    """V2 orchestrator (ORCHESTRATOR_VERSION=v2): parallel scheduling preserves trace_id."""

    @pytest.fixture(autouse=True)
    def _enable_v2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ORCHESTRATOR_VERSION", "v2")

    def test_all_steps_succeed_with_trace_continuity(self) -> None:
        plan = _multi_agent_plan()
        executor = _build_executor()
        orchestrator = create_orchestrator(executor=executor)

        before = _audit_ring_snapshot()
        results = orchestrator.run_plan(plan)
        after = _audit_ring_snapshot()

        # All three steps complete (V2 parallel scheduling respects depends_on)
        ok_results = [r for r in results if r["status"] == "ok"]
        assert len(ok_results) == 3

        # Agent responses echo back trace_id
        agent_results = [r for r in ok_results if "response" in r.get("result", {})]
        for r in agent_results:
            assert r["result"]["response"]["trace_id"] == TRACE_ID

        # Every audit event carries trace_id
        new_events = [evt for evt in after if evt not in before]
        assert len(new_events) > 0
        for evt in new_events:
            assert evt.get("trace_id") == TRACE_ID, (
                f"Event {evt['event_type']} missing trace_id: {evt}"
            )

    def test_request_response_events_for_both_agents(self) -> None:
        plan = _multi_agent_plan()
        executor = _build_executor()
        orchestrator = create_orchestrator(executor=executor)

        before = _audit_ring_snapshot()
        orchestrator.run_plan(plan)
        after = _audit_ring_snapshot()

        new_events = [evt for evt in after if evt not in before]
        requests = [e for e in new_events if e["event_type"] == AGENT_REQUEST_CREATED]
        responses = [e for e in new_events if e["event_type"] == AGENT_RESPONSE_CREATED]

        assert len(requests) == 2
        assert len(responses) == 2

        recipients = {e["payload"]["details"]["recipient"] for e in requests}
        assert "ingest-agent" in recipients
        assert "review-agent" in recipients

    def test_v2_respects_dependency_order(self) -> None:
        """step-2 depends on step-1; V2 must execute step-1 first."""
        plan = _multi_agent_plan()
        executor = _build_executor()
        orchestrator = create_orchestrator(executor=executor)

        results = orchestrator.run_plan(plan)
        ok_ids = [r["step_id"] for r in results if r["status"] == "ok"]

        # step-1 must appear before step-2 in results (dependency constraint)
        assert ok_ids.index("step-1") < ok_ids.index("step-2")
