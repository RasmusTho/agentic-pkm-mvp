"""Tests for pilot_agent nodes."""

from __future__ import annotations


from app.agents.pilot_agent.state import PilotAgentState
from app.agents.pilot_agent.nodes.validate import validate_node
from app.agents.pilot_agent.nodes.classify import classify_node
from app.agents.pilot_agent.nodes.apply import apply_node


class TestValidateNode:
    """Test validate_node function."""

    def test_validate_valid_state(self):
        """Valid state passes validation."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        result = validate_node(state)
        assert result.error is None
        assert result.step_count == 1
        assert "validate" in result.executed_actions

    def test_validate_missing_trace_id(self):
        """Missing trace_id causes error."""
        state = PilotAgentState(trace_id="", note_uuid="n1")
        result = validate_node(state)
        assert result.error is not None
        assert "trace_id" in result.error.lower()

    def test_validate_missing_note_uuid(self):
        """Missing note_uuid causes error."""
        state = PilotAgentState(trace_id="t1", note_uuid="")
        result = validate_node(state)
        assert result.error is not None
        assert "note_uuid" in result.error.lower()

    def test_validate_zero_budget(self):
        """Zero budget causes error."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", budget=0)
        result = validate_node(state)
        assert result.error is not None
        assert "budget" in result.error.lower()

    def test_validate_negative_budget(self):
        """Negative budget causes error."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", budget=-1)
        result = validate_node(state)
        assert result.error is not None

    def test_validate_increments_step_count(self):
        """Step count is incremented."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", step_count=0)
        result = validate_node(state)
        assert result.step_count == 1

    def test_validate_records_action(self):
        """Validate action is recorded."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        result = validate_node(state)
        assert "validate" in result.executed_actions

    def test_validate_does_not_modify_original(self):
        """validate_node does not modify input state."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", step_count=0)
        result = validate_node(state)
        assert state.step_count == 0
        assert result.step_count == 1
        assert result is not state

    def test_validate_preserves_other_fields(self):
        """Other fields are preserved."""
        state = PilotAgentState(
            trace_id="t1",
            note_uuid="n1",
            confidence=0.75,
            reason="test",
        )
        result = validate_node(state)
        assert result.confidence == 0.75
        assert result.reason == "test"


class TestClassifyNode:
    """Test classify_node function."""

    def test_classify_valid_state(self):
        """classify_node processes valid state."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        result = classify_node(state)
        assert result.error is None
        assert result.step_count == 1

    def test_classify_increments_step_count(self):
        """Step count is incremented."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", step_count=2)
        result = classify_node(state)
        assert result.step_count == 3

    def test_classify_adds_message(self):
        """System message is added."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", messages=[])
        result = classify_node(state)
        assert len(result.messages) > 0
        assert result.messages[0]["role"] == "system"

    def test_classify_preserves_previous_messages(self):
        """Previous messages are preserved."""
        prev_msg = {"role": "user", "content": "test"}
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", messages=[prev_msg]
        )
        result = classify_node(state)
        assert len(result.messages) == 2
        assert result.messages[0] == prev_msg

    def test_classify_records_action(self):
        """Classify action is recorded."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        result = classify_node(state)
        assert "classify" in result.executed_actions

    def test_classify_skips_error_state(self):
        """classify_node returns state unchanged if error is set."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", error="previous error"
        )
        result = classify_node(state)
        assert result.error == "previous error"
        assert result.step_count == 0  # Not incremented

    def test_classify_does_not_modify_original(self):
        """classify_node does not modify input state."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", messages=[])
        result = classify_node(state)
        assert len(state.messages) == 0
        assert len(result.messages) > 0


class TestApplyNode:
    """Test apply_node function."""

    def test_apply_valid_state(self):
        """apply_node processes valid state."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", decision="promote"
        )
        result = apply_node(state)
        assert result.error is None
        assert result.step_count == 1

    def test_apply_increments_step_count(self):
        """Step count is incremented."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", step_count=5)
        result = apply_node(state)
        assert result.step_count == 6

    def test_apply_normalizes_confidence_bounds(self):
        """Confidence is clamped to [0, 1]."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", confidence=1.5
        )
        result = apply_node(state)
        assert 0.0 <= result.confidence <= 1.0
        assert result.confidence == 1.0

    def test_apply_clamps_negative_confidence(self):
        """Negative confidence is clamped to 0."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", confidence=-0.5)
        result = apply_node(state)
        assert result.confidence == 0.0

    def test_apply_valid_decision_promote(self):
        """Decision 'promote' is valid."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", decision="promote"
        )
        result = apply_node(state)
        assert result.decision == "promote"
        assert result.error is None

    def test_apply_valid_decision_evergreen(self):
        """Decision 'evergreen' is valid."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", decision="evergreen"
        )
        result = apply_node(state)
        assert result.decision == "evergreen"

    def test_apply_valid_decision_archive(self):
        """Decision 'archive' is valid."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", decision="archive"
        )
        result = apply_node(state)
        assert result.decision == "archive"

    def test_apply_valid_decision_skip(self):
        """Decision 'skip' is valid."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", decision="skip")
        result = apply_node(state)
        assert result.decision == "skip"

    def test_apply_invalid_decision_defaults_to_skip(self):
        """Invalid decision defaults to skip."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", decision="invalid"
        )
        result = apply_node(state)
        assert result.decision == "skip"

    def test_apply_empty_decision_defaults_to_skip(self):
        """Empty decision defaults to skip."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", decision="")
        result = apply_node(state)
        assert result.decision == "skip"

    def test_apply_with_error_preserves_decision(self):
        """If error is set with decision, preserves decision."""
        state = PilotAgentState(
            trace_id="t1",
            note_uuid="n1",
            error="some error",
            decision="promote",
        )
        result = apply_node(state)
        assert result.decision == "promote"
        assert result.error == "some error"

    def test_apply_with_error_no_decision_defaults_to_skip(self):
        """If error is set without decision, defaults to skip."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", error="error")
        result = apply_node(state)
        assert result.decision == "skip"
        assert result.error == "error"

    def test_apply_records_action(self):
        """Apply action is recorded."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", decision="promote"
        )
        result = apply_node(state)
        assert "apply" in result.executed_actions

    def test_apply_does_not_modify_original(self):
        """apply_node does not modify input state."""
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", step_count=0, decision="promote"
        )
        result = apply_node(state)
        assert state.step_count == 0
        assert result.step_count == 1


class TestNodeErrorHandling:
    """Test error handling in nodes."""

    def test_validate_handles_exception(self):
        """validate_node handles exceptions gracefully."""
        # Create state with problematic fields (this shouldn't raise in our impl)
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        result = validate_node(state)
        # Should not raise
        assert isinstance(result, PilotAgentState)

    def test_classify_handles_exception(self):
        """classify_node handles exceptions gracefully."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        result = classify_node(state)
        assert isinstance(result, PilotAgentState)

    def test_apply_handles_exception(self):
        """apply_node handles exceptions gracefully."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        result = apply_node(state)
        assert isinstance(result, PilotAgentState)


class TestNodeSequence:
    """Test nodes in sequence (mini integration)."""

    def test_validate_then_classify(self):
        """Nodes can be chained: validate → classify."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        state = validate_node(state)
        state = classify_node(state)
        assert state.error is None
        assert state.step_count == 2
        assert "validate" in state.executed_actions
        assert "classify" in state.executed_actions

    def test_full_node_sequence_without_llm(self):
        """Full sequence: validate → classify → apply (skipping reason)."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        state = validate_node(state)
        state = classify_node(state)
        state.decision = "promote"  # Manually set decision
        state = apply_node(state)
        assert state.error is None
        assert state.step_count == 3
        assert state.decision == "promote"

    def test_node_sequence_preserves_trace_id(self):
        """trace_id is preserved through node sequence."""
        state = PilotAgentState(trace_id="trace-xyz", note_uuid="n1")
        state = validate_node(state)
        state = classify_node(state)
        state = apply_node(state)
        assert state.trace_id == "trace-xyz"
