"""Tests for pilot_agent event handling."""

from __future__ import annotations

import pytest

from app.agents.pilot_agent.state import PilotAgentState
from app.agents.pilot_agent.events import (
    state_to_event,
    PROMOTION_APPROVED,
    PROMOTION_DEFERRED,
    PROMOTION_ARCHIVED,
    PROMOTION_SKIPPED,
)
from app.events.schema import OutboxEvent


class TestStateToEvent:
    """Test state_to_event conversion."""

    def test_convert_promote_decision(self):
        """Promote decision maps to PROMOTION_APPROVED event."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", decision="promote"
        )
        event = state_to_event(state)
        assert event.event == PROMOTION_APPROVED

    def test_convert_evergreen_decision(self):
        """Evergreen decision maps to PROMOTION_DEFERRED event."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", decision="evergreen"
        )
        event = state_to_event(state)
        assert event.event == PROMOTION_DEFERRED

    def test_convert_archive_decision(self):
        """Archive decision maps to PROMOTION_ARCHIVED event."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", decision="archive"
        )
        event = state_to_event(state)
        assert event.event == PROMOTION_ARCHIVED

    def test_convert_skip_decision(self):
        """Skip decision maps to PROMOTION_SKIPPED event."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", decision="skip")
        event = state_to_event(state)
        assert event.event == PROMOTION_SKIPPED

    def test_convert_empty_decision_defaults_to_skip(self):
        """Empty decision defaults to PROMOTION_SKIPPED."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", decision="")
        event = state_to_event(state)
        assert event.event == PROMOTION_SKIPPED

    def test_convert_invalid_decision_defaults_to_skip(self):
        """Invalid decision defaults to PROMOTION_SKIPPED."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", decision="invalid"
        )
        event = state_to_event(state)
        assert event.event == PROMOTION_SKIPPED


class TestEventPayload:
    """Test event payload structure."""

    def test_payload_includes_note_uuid(self):
        """Payload includes note_uuid."""
        state = PilotAgentState(trace_id="t1", note_uuid="n-abc")
        event = state_to_event(state)
        assert event.payload["note_uuid"] == "n-abc"

    def test_payload_includes_decision(self):
        """Payload includes decision."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", decision="promote"
        )
        event = state_to_event(state)
        assert event.payload["decision"] == "promote"

    def test_payload_includes_reasoning(self):
        """Payload includes reasoning."""
        state = PilotAgentState(
            trace_id="t1",
            note_uuid="n1",
            reason="Test reasoning",
        )
        event = state_to_event(state)
        assert event.payload["reasoning"] == "Test reasoning"

    def test_payload_includes_confidence(self):
        """Payload includes confidence."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", confidence=0.85
        )
        event = state_to_event(state)
        assert event.payload["confidence"] == 0.85

    def test_payload_includes_steps(self):
        """Payload includes step count."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", step_count=3)
        event = state_to_event(state)
        assert event.payload["steps"] == 3

    def test_payload_includes_error_when_present(self):
        """Payload includes error when set."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", error="test error"
        )
        event = state_to_event(state)
        assert event.payload["error"] == "test error"

    def test_payload_excludes_error_when_absent(self):
        """Payload excludes error when not set."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", error=None)
        event = state_to_event(state)
        assert "error" not in event.payload


class TestEventMetadata:
    """Test event metadata structure."""

    def test_meta_includes_telemetry(self):
        """Meta includes telemetry section."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        event = state_to_event(state)
        assert "telemetry" in event.meta

    def test_telemetry_includes_steps(self):
        """Telemetry includes steps."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", step_count=2)
        event = state_to_event(state)
        assert event.meta["telemetry"]["steps"] == 2

    def test_telemetry_includes_budget_remaining(self):
        """Telemetry includes budget remaining."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", budget=10, step_count=3
        )
        event = state_to_event(state)
        assert event.meta["telemetry"]["budget_remaining"] == 7

    def test_telemetry_includes_executed_actions(self):
        """Telemetry includes executed actions."""
        state = PilotAgentState(
            trace_id="t1",
            note_uuid="n1",
            executed_actions=["validate", "classify"],
        )
        event = state_to_event(state)
        assert event.meta["telemetry"]["executed_actions"] == [
            "validate",
            "classify",
        ]

    def test_telemetry_includes_error_when_present(self):
        """Telemetry includes error when set."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", error="test error"
        )
        event = state_to_event(state)
        assert event.meta["telemetry"]["error"] == "test error"

    def test_telemetry_excludes_error_when_absent(self):
        """Telemetry excludes error when not set."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", error=None)
        event = state_to_event(state)
        assert "error" not in event.meta["telemetry"]


class TestEventEnvelope:
    """Test Outbox event envelope."""

    def test_event_has_required_fields(self):
        """Event has all required fields."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        event = state_to_event(state)
        assert hasattr(event, "event")
        assert hasattr(event, "trace_id")
        assert hasattr(event, "source")
        assert hasattr(event, "payload")
        assert hasattr(event, "meta")

    def test_event_preserves_trace_id(self):
        """Event preserves trace_id from state."""
        state = PilotAgentState(trace_id="trace-xyz", note_uuid="n1")
        event = state_to_event(state)
        assert event.trace_id == "trace-xyz"

    def test_event_has_source_pilot_agent(self):
        """Event source is pilot_agent."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        event = state_to_event(state)
        assert event.source == "pilot_agent"

    def test_event_has_timestamp(self):
        """Event has timestamp."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        event = state_to_event(state)
        assert event.timestamp is not None
        assert isinstance(event.timestamp, str)

    def test_event_has_event_id(self):
        """Event has event_id."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        event = state_to_event(state)
        assert event.event_id is not None
        assert isinstance(event.event_id, str)

    def test_event_id_can_be_specified(self):
        """Custom event_id can be provided."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        custom_id = "custom-event-123"
        event = state_to_event(state, event_id=custom_id)
        assert event.event_id == custom_id

    def test_event_id_auto_generated_if_not_provided(self):
        """event_id is auto-generated if not provided."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        event1 = state_to_event(state)
        event2 = state_to_event(state)
        assert event1.event_id != event2.event_id


class TestEventTypeConstants:
    """Test event type constants."""

    def test_promotion_approved_constant(self):
        """PROMOTION_APPROVED constant is defined."""
        assert PROMOTION_APPROVED == "promotion.approved"

    def test_promotion_deferred_constant(self):
        """PROMOTION_DEFERRED constant is defined."""
        assert PROMOTION_DEFERRED == "promotion.deferred"

    def test_promotion_archived_constant(self):
        """PROMOTION_ARCHIVED constant is defined."""
        assert PROMOTION_ARCHIVED == "promotion.archived"

    def test_promotion_skipped_constant(self):
        """PROMOTION_SKIPPED constant is defined."""
        assert PROMOTION_SKIPPED == "promotion.skipped"


class TestEventComplete:
    """Integration tests for complete event flow."""

    def test_full_state_to_event_flow(self):
        """Complete state to event conversion works."""
        state = PilotAgentState(
            trace_id="trace-complete",
            note_uuid="note-complete",
            decision="promote",
            confidence=0.9,
            reason="High quality note",
            step_count=4,
            budget=10,
            error=None,
            executed_actions=["validate", "classify", "reason", "apply"],
        )
        event = state_to_event(state, event_id="evt-123")

        # Verify event structure
        assert event.event == "promotion.approved"
        assert event.trace_id == "trace-complete"
        assert event.source == "pilot_agent"
        assert event.event_id == "evt-123"

        # Verify payload
        assert event.payload["note_uuid"] == "note-complete"
        assert event.payload["decision"] == "promote"
        assert event.payload["confidence"] == 0.9
        assert event.payload["reasoning"] == "High quality note"
        assert event.payload["steps"] == 4

        # Verify meta
        assert event.meta["telemetry"]["steps"] == 4
        assert event.meta["telemetry"]["budget_remaining"] == 6
        assert len(event.meta["telemetry"]["executed_actions"]) == 4

    def test_error_state_to_event(self):
        """Error state produces valid event."""
        state = PilotAgentState(
            trace_id="trace-error",
            note_uuid="note-error",
            error="LLM unavailable",
            decision="skip",
        )
        event = state_to_event(state)

        assert event.event == "promotion.skipped"
        assert event.payload["error"] == "LLM unavailable"
        assert event.meta["telemetry"]["error"] == "LLM unavailable"

    def test_minimal_state_to_event(self):
        """Minimal state produces valid event."""
        state = PilotAgentState(trace_id="t", note_uuid="n")
        event = state_to_event(state)

        # Should default to skip
        assert event.event == "promotion.skipped"
        assert event.payload["note_uuid"] == "n"
        assert event.trace_id == "t"
