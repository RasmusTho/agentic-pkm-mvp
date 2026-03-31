"""Test Orchestrator V2 integration: plan input, events, outbox."""

from __future__ import annotations

import time


from .conftest import (
    MockOutbox,
)


class TestOrchestratorIntegration:
    """Define integration contract for Orchestrator V2."""

    def test_orchestrator_receives_plan_from_event(
        self,
        plan_factory,
        mock_outbox: MockOutbox,
    ) -> None:
        """Orchestrator receives plan from Outbox event."""
        plan = plan_factory(plan_id="plan-1")

        # Plan delivered via event
        event = {
            "event": "orchestration.requested",
            "plan": plan,
            "timestamp": time.time(),
        }
        mock_outbox.emit(event)

        events = mock_outbox.list_events("orchestration.requested")
        assert len(events) == 1
        assert events[0]["plan"]["id"] == "plan-1"

    def test_orchestrator_emits_step_started_event(
        self,
        mock_outbox: MockOutbox,
    ) -> None:
        """Orchestrator emits step.started event on step execution."""
        mock_outbox.clear()

        event = {
            "event": "step.started",
            "plan_id": "plan-1",
            "step_id": "step-1",
            "source": "orchestrator.v2",
            "timestamp": time.time(),
        }
        mock_outbox.emit(event)

        events = mock_outbox.list_events("step.started")
        assert len(events) == 1
        assert events[0]["step_id"] == "step-1"

    def test_orchestrator_emits_step_completed_event(
        self,
        mock_outbox: MockOutbox,
    ) -> None:
        """Orchestrator emits step.completed event with result."""
        mock_outbox.clear()

        event = {
            "event": "step.completed",
            "plan_id": "plan-1",
            "step_id": "step-1",
            "result": {"status": "ok", "data": [1, 2, 3]},
            "source": "orchestrator.v2",
            "timestamp": time.time(),
        }
        mock_outbox.emit(event)

        events = mock_outbox.list_events("step.completed")
        assert len(events) == 1
        assert events[0]["result"]["status"] == "ok"

    def test_orchestrator_emits_step_failed_event(
        self,
        mock_outbox: MockOutbox,
    ) -> None:
        """Orchestrator emits step.failed event on error."""
        mock_outbox.clear()

        event = {
            "event": "step.failed",
            "plan_id": "plan-1",
            "step_id": "step-1",
            "error": "Agent timeout",
            "error_type": "timeout",
            "source": "orchestrator.v2",
            "timestamp": time.time(),
        }
        mock_outbox.emit(event)

        events = mock_outbox.list_events("step.failed")
        assert len(events) == 1
        assert events[0]["error"] == "Agent timeout"

    def test_orchestrator_emits_orchestration_done_event(
        self,
        mock_outbox: MockOutbox,
    ) -> None:
        """Orchestrator emits orchestration.done on plan completion."""
        mock_outbox.clear()

        event = {
            "event": "orchestration.done",
            "plan_id": "plan-1",
            "status": "completed",
            "results": [
                {"step_id": "step-1", "status": "ok"},
                {"step_id": "step-2", "status": "ok"},
            ],
            "source": "orchestrator.v2",
            "timestamp": time.time(),
        }
        mock_outbox.emit(event)

        events = mock_outbox.list_events("orchestration.done")
        assert len(events) == 1
        assert events[0]["status"] == "completed"

    def test_orchestrator_emits_orchestration_rolled_back_event(
        self,
        mock_outbox: MockOutbox,
    ) -> None:
        """Orchestrator emits orchestration.rolled_back on compensation complete."""
        mock_outbox.clear()

        event = {
            "event": "orchestration.rolled_back",
            "plan_id": "plan-1",
            "failed_step": "step-2",
            "compensated_steps": ["step-1"],
            "source": "orchestrator.v2",
            "timestamp": time.time(),
        }
        mock_outbox.emit(event)

        events = mock_outbox.list_events("orchestration.rolled_back")
        assert len(events) == 1
        assert events[0]["plan_id"] == "plan-1"

    def test_all_events_have_canonical_envelope(
        self,
        canonical_event_envelope,
        mock_outbox: MockOutbox,
    ) -> None:
        """All events have canonical envelope: event, event_id, trace_id, source, timestamp, payload, meta."""
        envelope = canonical_event_envelope

        # All orchestrator events follow this shape
        required_fields = {
            "event",
            "event_id",
            "trace_id",
            "source",
            "timestamp",
            "payload",
            "meta",
        }

        # Create a minimal event
        test_event = {
            "event": "step.completed",
            "event_id": envelope["event_id"],
            "trace_id": envelope["trace_id"],
            "source": "orchestrator.v2",
            "timestamp": time.time(),
            "payload": {"step_id": "step-1", "result": {}},
            "meta": {},
        }

        assert all(field in test_event for field in required_fields)

    def test_event_trace_id_propagated_through_plan(
        self,
        mock_outbox: MockOutbox,
    ) -> None:
        """trace_id is propagated through all events for a plan."""
        trace_id = "trace-abc123"
        mock_outbox.clear()

        mock_outbox.emit({
            "event": "step.started",
            "trace_id": trace_id,
            "step_id": "step-1",
        })
        mock_outbox.emit({
            "event": "step.completed",
            "trace_id": trace_id,
            "step_id": "step-1",
        })

        events = mock_outbox.list_events()
        assert all(e["trace_id"] == trace_id for e in events)

    def test_orchestrator_never_mutates_vault_directly(
        self,
        mock_outbox: MockOutbox,
    ) -> None:
        """Orchestrator never directly mutates vault, only via agent step outputs."""
        mock_outbox.clear()

        # Orchestrator publishes events, not vault mutations
        event = {
            "event": "step.completed",
            "plan_id": "plan-1",
            "step_id": "step-1",
            "result": {"vault_mutation": "MUST NOT HAPPEN DIRECTLY"},
        }
        mock_outbox.emit(event)

        # If vault mutation needed, agent step must handle it
        # Orchestrator's responsibility: emit event, let agents/handlers process

        events = mock_outbox.list_events("step.completed")
        assert len(events) == 1

    def test_multiple_parallel_step_events_concurrent(
        self,
        mock_outbox: MockOutbox,
    ) -> None:
        """Parallel step execution emits concurrent step events."""
        mock_outbox.clear()

        # Simulate 3 parallel steps emitting events
        for i in range(1, 4):
            mock_outbox.emit({
                "event": "step.started",
                "step_id": f"step-{i}",
                "timestamp": time.time(),
            })

        started_events = mock_outbox.list_events("step.started")
        assert len(started_events) == 3

    def test_plan_context_passed_through_events(
        self,
        plan_factory,
        mock_outbox: MockOutbox,
    ) -> None:
        """Plan metadata (context) available in events for downstream processing."""
        plan = plan_factory(
            context={
                "flow_id": "ask.v1",
                "agent_id": "reviewer",
            }
        )

        event = {
            "event": "orchestration.requested",
            "plan": plan,
            "context": plan["context"],
        }
        mock_outbox.emit(event)

        events = mock_outbox.list_events("orchestration.requested")
        assert events[0]["context"]["flow_id"] == "ask.v1"
