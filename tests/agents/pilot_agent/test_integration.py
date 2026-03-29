"""Integration tests for pilot_agent."""

from __future__ import annotations

import pytest

from app.agents.pilot_agent.state import PilotAgentState
from app.agents.pilot_agent.graph import run_promotion_graph
from app.agents.pilot_agent.events import state_to_event
from app.events.schema import make_outbox_event


class TestFullWorkflow:
    """Test complete workflow: event → graph → event."""

    def test_event_to_state_to_graph_to_event(self):
        """Complete workflow: event → state → graph → event."""
        # Create input event
        input_event = make_outbox_event(
            "promotion.intent.created",
            source="panel_agent",
            trace_id="trace-workflow-123",
            payload={
                "note_uuid": "note-workflow-456",
                "confidence": 0.75,
            },
        )

        # Parse event to state
        state = PilotAgentState.from_event(input_event)
        assert state.trace_id == input_event.trace_id
        assert state.note_uuid == "note-workflow-456"

        # Run graph
        final_state = run_promotion_graph(state)

        # Verify graph ran
        assert final_state is not None
        assert final_state.trace_id == state.trace_id

        # Convert state to output event
        output_event = state_to_event(final_state)

        # Verify output event
        assert output_event.trace_id == final_state.trace_id
        assert output_event.payload["note_uuid"] == final_state.note_uuid

    def test_workflow_preserves_trace_id(self):
        """trace_id is preserved through entire workflow."""
        trace_id = "trace-integration-xyz"
        event = make_outbox_event(
            "promotion.intent.created",
            source="test",
            trace_id=trace_id,
            payload={"note_uuid": "note-int"},
        )

        state = PilotAgentState.from_event(event)
        final_state = run_promotion_graph(state)
        output_event = state_to_event(final_state)

        assert output_event.trace_id == trace_id

    def test_workflow_produces_valid_output_event(self):
        """Workflow produces valid Outbox event."""
        event = make_outbox_event(
            "promotion.intent.created",
            source="test",
            payload={"note_uuid": "n1"},
        )

        state = PilotAgentState.from_event(event)
        final_state = run_promotion_graph(state)
        output_event = state_to_event(final_state)

        # Check required fields
        assert output_event.event in {
            "promotion.approved",
            "promotion.deferred",
            "promotion.archived",
            "promotion.skipped",
        }
        assert output_event.trace_id
        assert output_event.source == "pilot_agent"
        assert output_event.payload is not None
        assert output_event.meta is not None


class TestWorkflowVariations:
    """Test workflow with different input variations."""

    def test_workflow_with_high_confidence(self):
        """Workflow with high confidence input."""
        event = make_outbox_event(
            "promotion.intent.created",
            source="test",
            payload={"note_uuid": "note-high", "confidence": 0.95},
        )

        state = PilotAgentState.from_event(event)
        final_state = run_promotion_graph(state)
        output_event = state_to_event(final_state)

        assert output_event is not None
        assert output_event.payload["confidence"] >= 0.0

    def test_workflow_with_low_confidence(self):
        """Workflow with low confidence input."""
        event = make_outbox_event(
            "promotion.intent.created",
            source="test",
            payload={"note_uuid": "note-low", "confidence": 0.1},
        )

        state = PilotAgentState.from_event(event)
        final_state = run_promotion_graph(state)
        output_event = state_to_event(final_state)

        assert output_event is not None

    def test_workflow_with_minimal_payload(self):
        """Workflow with minimal payload."""
        event = make_outbox_event(
            "promotion.intent.created",
            source="test",
            payload={"note_uuid": "note-minimal"},
        )

        state = PilotAgentState.from_event(event)
        final_state = run_promotion_graph(state)
        output_event = state_to_event(final_state)

        assert output_event is not None
        assert output_event.payload["note_uuid"] == "note-minimal"

    def test_workflow_with_source_ref(self):
        """Workflow preserves source reference."""
        event = make_outbox_event(
            "promotion.intent.created",
            source="test",
            payload={
                "note_uuid": "note-ref",
                "source_ref": "panel-action-123",
            },
        )

        state = PilotAgentState.from_event(event)
        assert state.source_ref == "panel-action-123"

        final_state = run_promotion_graph(state)
        assert final_state.source_ref == "panel-action-123"


class TestMultipleWorkflows:
    """Test running multiple workflows in sequence."""

    def test_two_independent_workflows(self):
        """Two independent workflows produce independent results."""
        # First workflow
        event1 = make_outbox_event(
            "promotion.intent.created",
            source="test",
            trace_id="trace1",
            payload={"note_uuid": "note1", "confidence": 0.8},
        )
        state1 = PilotAgentState.from_event(event1)
        final_state1 = run_promotion_graph(state1)
        output_event1 = state_to_event(final_state1)

        # Second workflow
        event2 = make_outbox_event(
            "promotion.intent.created",
            source="test",
            trace_id="trace2",
            payload={"note_uuid": "note2", "confidence": 0.3},
        )
        state2 = PilotAgentState.from_event(event2)
        final_state2 = run_promotion_graph(state2)
        output_event2 = state_to_event(final_state2)

        # Verify independence
        assert output_event1.trace_id != output_event2.trace_id
        assert (
            output_event1.payload["note_uuid"]
            != output_event2.payload["note_uuid"]
        )

    def test_sequential_workflows_use_fresh_state(self):
        """Sequential workflows don't share state."""
        for i in range(3):
            event = make_outbox_event(
                "promotion.intent.created",
                source="test",
                payload={"note_uuid": f"note-{i}"},
            )
            state = PilotAgentState.from_event(event)
            final_state = run_promotion_graph(state)

            # Each should execute successfully
            assert final_state.note_uuid == f"note-{i}"


class TestWorkflowErrorRecovery:
    """Test workflow with error conditions."""

    def test_workflow_with_invalid_state(self):
        """Workflow handles invalid state gracefully."""
        state = PilotAgentState(trace_id="", note_uuid="")
        final_state = run_promotion_graph(state)

        # Should handle gracefully
        assert final_state is not None
        assert final_state.error is not None or final_state.decision is not None

    def test_workflow_creates_result_event_on_error(self):
        """Workflow creates result event even on error."""
        state = PilotAgentState(trace_id="t", note_uuid="")
        final_state = run_promotion_graph(state)
        output_event = state_to_event(final_state)

        # Should still produce valid event
        assert output_event is not None
        assert output_event.trace_id == "t"


class TestWorkflowTelemetry:
    """Test workflow telemetry collection."""

    def test_workflow_collects_step_count(self):
        """Workflow collects step count."""
        event = make_outbox_event(
            "promotion.intent.created",
            source="test",
            payload={"note_uuid": "note-telem"},
        )

        state = PilotAgentState.from_event(event)
        initial_steps = state.step_count

        final_state = run_promotion_graph(state)
        output_event = state_to_event(final_state)

        # Step count should be in telemetry
        assert output_event.meta["telemetry"]["steps"] == final_state.step_count

    def test_workflow_collects_executed_actions(self):
        """Workflow collects executed actions."""
        event = make_outbox_event(
            "promotion.intent.created",
            source="test",
            payload={"note_uuid": "note-actions"},
        )

        state = PilotAgentState.from_event(event)
        final_state = run_promotion_graph(state)
        output_event = state_to_event(final_state)

        # Actions should be in telemetry
        assert "executed_actions" in output_event.meta["telemetry"]

    def test_workflow_collects_budget_tracking(self):
        """Workflow tracks budget."""
        event = make_outbox_event(
            "promotion.intent.created",
            source="test",
            payload={"note_uuid": "note-budget"},
        )

        state = PilotAgentState.from_event(event)
        state = state.copy(update={"budget": 10})

        final_state = run_promotion_graph(state)
        output_event = state_to_event(final_state)

        # Budget remaining should be computed
        remaining = output_event.meta["telemetry"]["budget_remaining"]
        assert remaining == (state.budget - final_state.step_count)


class TestEventRoundtrip:
    """Test event serialization roundtrip."""

    def test_event_serializable(self):
        """Output event is serializable."""
        import json

        event = make_outbox_event(
            "promotion.intent.created",
            source="test",
            payload={"note_uuid": "n1"},
        )

        state = PilotAgentState.from_event(event)
        final_state = run_promotion_graph(state)
        output_event = state_to_event(final_state)

        # Should be serializable to JSON
        json_str = output_event.model_dump_json()
        assert json_str is not None

    def test_event_deserializable(self):
        """Output event is deserializable."""
        from app.events.schema import OutboxEvent

        event = make_outbox_event(
            "promotion.intent.created",
            source="test",
            payload={"note_uuid": "n1"},
        )

        state = PilotAgentState.from_event(event)
        final_state = run_promotion_graph(state)
        output_event = state_to_event(final_state)

        # Should be deserializable
        json_str = output_event.model_dump_json()
        restored = OutboxEvent.model_validate_json(json_str)
        assert restored.trace_id == output_event.trace_id
