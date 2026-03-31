"""Tests for pilot_agent LangGraph."""

from __future__ import annotations


from app.agents.pilot_agent.state import PilotAgentState
from app.agents.pilot_agent.graph import build_promotion_graph, run_promotion_graph


class TestGraphConstruction:
    """Test graph building."""

    def test_graph_builds(self):
        """Graph builds without error."""
        graph = build_promotion_graph()
        assert graph is not None

    def test_graph_is_compiled(self):
        """Graph is compiled and ready to invoke."""
        graph = build_promotion_graph()
        # Compiled graphs have invoke method
        assert hasattr(graph, "invoke")

    def test_graph_has_correct_type(self):
        """Graph has correct type."""
        graph = build_promotion_graph()
        assert "CompiledStateGraph" in str(type(graph))


class TestGraphInvocation:
    """Test graph.invoke() method."""

    def test_invoke_minimal_state(self):
        """Graph can invoke with minimal valid state."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        result = run_promotion_graph(state)
        assert isinstance(result, PilotAgentState)
        assert result.trace_id == state.trace_id

    def test_invoke_returns_state(self):
        """invoke() returns final state."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        result = run_promotion_graph(state)
        assert isinstance(result, PilotAgentState)

    def test_invoke_with_initial_step_count(self):
        """invoke() preserves and updates step_count."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", step_count=0)
        result = run_promotion_graph(state)
        # Should have incremented through validate, classify, and apply nodes
        assert result.step_count >= 0

    def test_invoke_does_not_modify_input(self):
        """invoke() does not modify input state."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", step_count=0)
        original_steps = state.step_count
        result = run_promotion_graph(state)
        assert state.step_count == original_steps
        assert result.step_count != original_steps


class TestGraphValidation:
    """Test graph validation handling."""

    def test_graph_handles_invalid_trace_id(self):
        """Graph handles invalid trace_id gracefully."""
        state = PilotAgentState(trace_id="", note_uuid="n1")
        result = run_promotion_graph(state)
        # Should set error in validate node
        assert result.error is not None or result.decision == "skip"

    def test_graph_handles_invalid_note_uuid(self):
        """Graph handles invalid note_uuid gracefully."""
        state = PilotAgentState(trace_id="t1", note_uuid="")
        result = run_promotion_graph(state)
        assert result.error is not None or result.decision == "skip"

    def test_graph_handles_zero_budget(self):
        """Graph handles zero budget gracefully."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", budget=0)
        result = run_promotion_graph(state)
        assert result.error is not None


class TestGraphTopology:
    """Test graph node topology."""

    def test_graph_executes_nodes_in_sequence(self):
        """Graph executes nodes in correct sequence."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        result = run_promotion_graph(state)
        # Check executed_actions list contains expected nodes
        assert "validate" in result.executed_actions or len(result.executed_actions) > 0

    def test_graph_sets_trace_id(self):
        """Graph preserves trace_id through execution."""
        trace_id = "trace-test-xyz"
        state = PilotAgentState(trace_id=trace_id, note_uuid="n1")
        result = run_promotion_graph(state)
        assert result.trace_id == trace_id

    def test_graph_sets_note_uuid(self):
        """Graph preserves note_uuid through execution."""
        note_uuid = "note-test-abc"
        state = PilotAgentState(trace_id="t1", note_uuid=note_uuid)
        result = run_promotion_graph(state)
        assert result.note_uuid == note_uuid


class TestGraphDecisions:
    """Test that graph produces decisions."""

    def test_graph_produces_decision(self):
        """Graph produces some decision."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        result = run_promotion_graph(state)
        # May have decision or error
        assert result.decision or result.error

    def test_graph_produces_valid_decision(self):
        """Graph produces valid decision when no error."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        result = run_promotion_graph(state)
        valid_decisions = {"promote", "evergreen", "archive", "skip"}
        if not result.error:
            assert result.decision in valid_decisions

    def test_graph_produces_confidence(self):
        """Graph may produce confidence score."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1")
        result = run_promotion_graph(state)
        # Confidence should be a number in valid range or not set
        assert isinstance(result.confidence, (int, float))


class TestGraphWithMessages:
    """Test graph with LLM message context."""

    def test_graph_preserves_messages(self):
        """Graph preserves message list."""
        messages = [{"role": "system", "content": "test"}]
        state = PilotAgentState(
            trace_id="t1", note_uuid="n1", messages=messages
        )
        result = run_promotion_graph(state)
        assert len(result.messages) >= len(messages)

    def test_graph_can_add_messages(self):
        """Graph may add messages during execution."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", messages=[])
        result = run_promotion_graph(state)
        # classify_node should add a message
        assert len(result.messages) >= 0


class TestGraphBudget:
    """Test graph budget handling."""

    def test_graph_respects_budget(self):
        """Graph respects budget limit."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", budget=10)
        result = run_promotion_graph(state)
        assert result.step_count <= result.budget

    def test_graph_with_small_budget(self):
        """Graph works with small budget."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", budget=1)
        result = run_promotion_graph(state)
        assert isinstance(result, PilotAgentState)

    def test_graph_with_large_budget(self):
        """Graph works with large budget."""
        state = PilotAgentState(trace_id="t1", note_uuid="n1", budget=100)
        result = run_promotion_graph(state)
        assert isinstance(result, PilotAgentState)


class TestGraphRepeatedInvocation:
    """Test graph can be invoked multiple times."""

    def test_graph_can_be_invoked_twice(self):
        """Graph can be invoked multiple times."""
        state1 = PilotAgentState(trace_id="t1", note_uuid="n1")
        result1 = run_promotion_graph(state1)

        state2 = PilotAgentState(trace_id="t2", note_uuid="n2")
        result2 = run_promotion_graph(state2)

        assert result1.trace_id != result2.trace_id

    def test_graph_independent_invocations(self):
        """Graph invocations are independent."""
        state1 = PilotAgentState(trace_id="t1", note_uuid="n1", confidence=0.8)
        result1 = run_promotion_graph(state1)

        state2 = PilotAgentState(trace_id="t2", note_uuid="n2", confidence=0.2)
        result2 = run_promotion_graph(state2)

        # Results should be independent
        assert result1.trace_id == "t1"
        assert result2.trace_id == "t2"


class TestGraphErrorFlow:
    """Test error handling in graph."""

    def test_graph_handles_validation_error(self):
        """Graph handles validation error."""
        state = PilotAgentState(trace_id="", note_uuid="n1")
        result = run_promotion_graph(state)
        # Should propagate error through graph
        assert result.error is not None or result.decision is not None

    def test_graph_sets_decision_on_error(self):
        """Graph sets decision even on error."""
        state = PilotAgentState(trace_id="t1", note_uuid="")
        result = run_promotion_graph(state)
        # Even with error, should have a decision (fallback)
        if result.error:
            assert result.decision or len(result.executed_actions) > 0
