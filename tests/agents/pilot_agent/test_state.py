"""Tests for PilotAgentState."""

from __future__ import annotations

import pytest

from app.agents.pilot_agent.state import PilotAgentState
from app.events.schema import make_outbox_event


class TestStateCreation:
    """Test basic state creation."""

    def test_create_with_required_fields(self):
        """State can be created with required fields."""
        state = PilotAgentState(trace_id="trace-123", note_uuid="note-456")
        assert state.trace_id == "trace-123"
        assert state.note_uuid == "note-456"
        assert state.budget == 10
        assert state.step_count == 0

    def test_create_with_all_fields(self):
        """State can be created with all fields."""
        state = PilotAgentState(
            trace_id="trace-789",
            note_uuid="note-abc",
            budget=5,
            step_count=2,
            confidence=0.85,
            reason="Test reason",
            decision="promote",
            error=None,
        )
        assert state.budget == 5
        assert state.step_count == 2
        assert state.confidence == 0.85
        assert state.reason == "Test reason"
        assert state.decision == "promote"
        assert state.error is None

    def test_default_values(self):
        """State has sensible defaults."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        assert state.budget == 10
        assert state.step_count == 0
        assert state.messages == []
        assert state.source_ref == ""
        assert state.confidence == 0.0
        assert state.reason == ""
        assert state.decision == ""
        assert state.executed_actions == []
        assert state.error is None


class TestStateCopy:
    """Test state.copy() method."""

    def test_copy_returns_new_instance(self):
        """copy() returns a new instance."""
        state1 = PilotAgentState(trace_id="t1", note_uuid="n1")
        state2 = state1.copy()
        assert state1 is not state2
        assert state1.trace_id == state2.trace_id

    def test_copy_with_single_update(self):
        """copy() with single field update."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", step_count=0)
        new_state = state.copy(update={"step_count": 1})
        assert state.step_count == 0
        assert new_state.step_count == 1

    def test_copy_with_multiple_updates(self):
        """copy() with multiple field updates."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        new_state = state.copy(
            update={
                "step_count": 5,
                "decision": "promote",
                "confidence": 0.9,
            }
        )
        assert new_state.step_count == 5
        assert new_state.decision == "promote"
        assert new_state.confidence == 0.9

    def test_copy_preserves_unmodified_fields(self):
        """copy() preserves fields not in update dict."""
        state = PilotAgentState(
            trace_id="t1",
            note_uuid="n1",
            reason="old reason",
            decision="skip",
        )
        new_state = state.copy(update={"step_count": 1})
        assert new_state.trace_id == state.trace_id
        assert new_state.reason == "old reason"
        assert new_state.decision == "skip"

    def test_copy_with_list_fields(self):
        """copy() properly handles list fields."""
        state = PilotAgentState(
            trace_id="t1",
            note_uuid="n1",
            executed_actions=["action1"],
        )
        new_state = state.copy(update={"executed_actions": ["action1", "action2"]})
        assert len(new_state.executed_actions) == 2
        assert "action2" in new_state.executed_actions
        # Original is unchanged
        assert len(state.executed_actions) == 1

    def test_copy_empty_update(self):
        """copy() with no update dict acts as shallow copy."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", budget=5)
        new_state = state.copy()
        assert new_state is not state
        assert new_state.budget == 5


class TestFromEvent:
    """Test PilotAgentState.from_event()."""

    def test_from_event_minimal(self):
        """from_event() with minimal event."""
        event = make_outbox_event(
            "test",
            source="test",
            trace_id="trace-123",
            payload={"note_uuid": "note-456"},
        )
        state = PilotAgentState.from_event(event)
        assert state.trace_id == "trace-123"
        assert state.note_uuid == "note-456"

    def test_from_event_full(self):
        """from_event() with all optional fields."""
        event = make_outbox_event(
            "test",
            source="test",
            trace_id="trace-abc",
            payload={
                "note_uuid": "note-xyz",
                "source_ref": "ref-123",
                "confidence": 0.85,
            },
        )
        state = PilotAgentState.from_event(event)
        assert state.trace_id == "trace-abc"
        assert state.note_uuid == "note-xyz"
        assert state.source_ref == "ref-123"
        assert state.confidence == 0.85

    def test_from_event_missing_note_uuid(self):
        """from_event() with missing note_uuid defaults to empty string."""
        event = make_outbox_event(
            "test",
            source="test",
            trace_id="trace-123",
            payload={},
        )
        state = PilotAgentState.from_event(event)
        assert state.note_uuid == ""

    def test_from_event_missing_confidence(self):
        """from_event() with missing confidence defaults to 0.0."""
        event = make_outbox_event(
            "test",
            source="test",
            trace_id="trace-123",
            payload={"note_uuid": "note-123"},
        )
        state = PilotAgentState.from_event(event)
        assert state.confidence == 0.0

    def test_from_event_invalid_confidence(self):
        """from_event() coerces invalid confidence to float."""
        event = make_outbox_event(
            "test",
            source="test",
            trace_id="trace-123",
            payload={
                "note_uuid": "note-123",
                "confidence": "0.75",  # String instead of float
            },
        )
        state = PilotAgentState.from_event(event)
        assert isinstance(state.confidence, float)
        assert state.confidence == 0.75

    def test_from_event_confidence_bounds(self):
        """from_event() allows any confidence value (bounds checked elsewhere)."""
        event = make_outbox_event(
            "test",
            source="test",
            trace_id="trace-123",
            payload={
                "note_uuid": "note-123",
                "confidence": 1.5,  # Out of bounds
            },
        )
        state = PilotAgentState.from_event(event)
        assert state.confidence == 1.5  # Not clamped in from_event


class TestStateMessages:
    """Test messages field (LLM conversation)."""

    def test_messages_default_empty(self):
        """messages field defaults to empty list."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        assert state.messages == []

    def test_messages_can_be_set(self):
        """messages can be set during creation."""
        messages = [{"role": "user", "content": "Hello"}]
        state = PilotAgentState(trace_id="t1", note_uuid="n1", messages=messages)
        assert len(state.messages) == 1
        assert state.messages[0]["role"] == "user"

    def test_messages_preserved_in_copy(self):
        """messages are preserved when copying without update."""
        messages = [{"role": "user", "content": "Hello"}]
        state1 = PilotAgentState(trace_id="t1", note_uuid="n1", messages=messages)
        state2 = state1.copy()
        assert state2.messages == messages

    def test_messages_not_shared_between_instances(self):
        """List fields are not shared between instances."""
        state1 = PilotAgentState(trace_id="t1", note_uuid="n1")
        state2 = state1.copy()
        state2.messages.append({"role": "assistant", "content": "Hi"})
        assert len(state1.messages) == 0
        assert len(state2.messages) == 1


class TestStateValidation:
    """Test state field validation."""

    def test_trace_id_required(self):
        """trace_id is required."""
        with pytest.raises(TypeError):
            PilotAgentState(note_uuid="n1")  # type: ignore

    def test_note_uuid_required(self):
        """note_uuid is required."""
        with pytest.raises(TypeError):
            PilotAgentState(trace_id="t1")  # type: ignore

    def test_confidence_bounds(self):
        """confidence can be any float (bounds checked in nodes)."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", confidence=2.0)
        assert state.confidence == 2.0

    def test_step_count_positive(self):
        """step_count can be any non-negative integer."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", step_count=100)
        assert state.step_count == 100

    def test_decision_any_string(self):
        """decision can be any string (validated in nodes)."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", decision="invalid")
        assert state.decision == "invalid"


class TestStateImmutability:
    """Test that dataclass immutability is enforced."""

    def test_state_fields_are_mutable(self):
        """Dataclass fields are mutable (not frozen)."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        state.step_count = 5
        assert state.step_count == 5

    def test_copy_creates_independent_lists(self):
        """Lists in copies are independent."""
        state1 = PilotAgentState(
            trace_id="t1", note_uuid="n1", executed_actions=["a"]
        )
        state2 = state1.copy()
        state2.executed_actions.append("b")
        assert len(state1.executed_actions) == 1
        assert len(state2.executed_actions) == 2
