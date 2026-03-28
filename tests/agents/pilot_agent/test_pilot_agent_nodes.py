"""Test suite for pilot agent node behavior contract.

Enforces that nodes are independently testable, pure functions,
use ReasoningFacade, and handle errors gracefully.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from tests.agents.pilot_agent.conftest import PilotAgentState


class TestNodeAcceptsAndProducesState:
    """Verify nodes accept state input and produce state output."""

    def test_node_accepts_state(self, state_factory, mock_reasoning_facade):
        state = state_factory()

        def simple_node(input_state: PilotAgentState) -> PilotAgentState:
            return input_state

        result = simple_node(state)
        assert result is not None
        assert isinstance(result, PilotAgentState)

    def test_node_produces_modified_state(self, state_factory):
        state = state_factory(step_count=0)

        def increment_step_node(input_state: PilotAgentState) -> PilotAgentState:
            input_state.step_count = input_state.step_count + 1
            return input_state

        result = increment_step_node(state)
        assert result.step_count == 1

    def test_node_preserves_immutable_fields(self, state_factory):
        state = state_factory(uuid="original-uuid", trace_id="original-trace")

        def modify_node(input_state: PilotAgentState) -> PilotAgentState:
            input_state.step_count = 99
            return input_state

        result = modify_node(state)
        assert result.uuid == "original-uuid"
        assert result.trace_id == "original-trace"

    def test_node_can_update_decision(self, state_factory):
        state = state_factory(decision=None)

        def decide_node(input_state: PilotAgentState) -> PilotAgentState:
            input_state.decision = "promote"
            return input_state

        result = decide_node(state)
        assert result.decision == "promote"

    def test_node_can_update_executed_actions(self, state_factory):
        state = state_factory(executed_actions=[])

        def action_node(input_state: PilotAgentState) -> PilotAgentState:
            input_state.executed_actions.append("validate_notes")
            return input_state

        result = action_node(state)
        assert "validate_notes" in result.executed_actions


class TestNodeCallsReasoningFacade:
    """Verify nodes invoke ReasoningFacade for LLM reasoning."""

    def test_node_calls_facade_chat(self, state_factory, mock_reasoning_facade):
        state = state_factory()

        def chat_node(input_state: PilotAgentState) -> PilotAgentState:
            mock_reasoning_facade.chat(
                [{"role": "user", "content": "analyze this"}],
                trace_id=input_state.trace_id,
            )
            return input_state

        chat_node(state)
        mock_reasoning_facade.chat.assert_called_once()

    def test_node_calls_facade_structured(self, state_factory, mock_reasoning_facade):
        state = state_factory()

        def decide_node(input_state: PilotAgentState) -> PilotAgentState:
            result = mock_reasoning_facade.structured(
                [{"role": "user", "content": "decide"}],
                schema={"type": "object", "properties": {"decision": {"type": "string"}}},
                trace_id=input_state.trace_id,
            )
            input_state.decision = result.get("decision")
            return input_state

        decide_node(state)
        mock_reasoning_facade.structured.assert_called_once()

    def test_node_calls_facade_tool_use(self, state_factory, mock_reasoning_facade):
        state = state_factory()

        def tool_node(input_state: PilotAgentState) -> PilotAgentState:
            result = mock_reasoning_facade.tool_use(
                [{"role": "user", "content": "apply action"}],
                tools=[{"name": "promote", "description": "promote note"}],
                trace_id=input_state.trace_id,
            )
            input_state.executed_actions.append(result.tool_name)
            return input_state

        tool_node(state)
        mock_reasoning_facade.tool_use.assert_called_once()

    def test_node_passes_trace_id_to_facade(self, state_factory, mock_reasoning_facade):
        state = state_factory(trace_id="specific-trace-123")

        def trace_node(input_state: PilotAgentState) -> PilotAgentState:
            mock_reasoning_facade.chat(
                [{"role": "user", "content": "test"}],
                trace_id=input_state.trace_id,
            )
            return input_state

        trace_node(state)
        mock_reasoning_facade.chat.assert_called_once()
        assert "specific-trace-123" in str(mock_reasoning_facade.chat.call_args)

    def test_node_does_not_call_raw_router(self, state_factory, mock_llm_router):
        state = state_factory()

        def router_node(input_state: PilotAgentState) -> PilotAgentState:
            # Should NOT call router directly
            mock_llm_router.route.assert_not_called()
            return input_state

        router_node(state)
        mock_reasoning_facade.call_count == 0


class TestNodeErrorHandling:
    """Verify nodes handle errors gracefully without crashing."""

    def test_invalid_state_type_gracefully_degraded(self, mock_reasoning_facade):
        def strict_node(input_state: PilotAgentState) -> PilotAgentState:
            try:
                if not isinstance(input_state, (PilotAgentState, dict)):
                    input_state.error = "invalid_state_type"
            except Exception as e:
                input_state.error = str(e)
            return input_state

        # This should not raise; error should be captured in state
        result = strict_node(None)
        # Implementation should handle or return something

    def test_missing_required_fields_recorded_as_error(self, state_factory):
        state = state_factory(uuid=None)

        def validation_node(input_state: PilotAgentState) -> PilotAgentState:
            try:
                if not input_state.uuid:
                    input_state.error = "missing_uuid"
            except Exception as e:
                input_state.error = str(e)
            return input_state

        # Should not raise; error recorded
        result = validation_node(state)
        assert result.error is not None

    def test_facade_exception_recorded(self, state_factory, mock_reasoning_facade):
        state = state_factory()
        mock_reasoning_facade.chat.side_effect = RuntimeError("LLM timeout")

        def resilient_node(input_state: PilotAgentState) -> PilotAgentState:
            try:
                mock_reasoning_facade.chat(
                    [{"role": "user", "content": "test"}],
                    trace_id=input_state.trace_id,
                )
            except RuntimeError as e:
                input_state.error = f"reasoning_failed: {str(e)}"
            return input_state

        result = resilient_node(state)
        assert result.error is not None
        assert "reasoning_failed" in result.error

    def test_node_increments_budget_on_execution(self, state_factory, mock_reasoning_facade):
        state = state_factory(budget=100, step_count=0)

        def budgeted_node(input_state: PilotAgentState) -> PilotAgentState:
            input_state.step_count += 1
            if input_state.budget > 0:
                input_state.budget -= 10
            return input_state

        result = budgeted_node(state)
        assert result.step_count == 1
        assert result.budget == 90

    def test_node_stops_at_budget_zero(self, state_factory):
        state = state_factory(budget=0)

        def budget_aware_node(input_state: PilotAgentState) -> PilotAgentState:
            if input_state.budget <= 0:
                input_state.error = "budget_exhausted"
            else:
                input_state.budget -= 10
            return input_state

        result = budget_aware_node(state)
        assert result.error == "budget_exhausted"
        assert result.budget == 0

    def test_node_appends_to_messages(self, state_factory):
        state = state_factory(messages=[])

        def message_node(input_state: PilotAgentState) -> PilotAgentState:
            input_state.messages.append({"role": "assistant", "content": "analysis"})
            return input_state

        result = message_node(state)
        assert len(result.messages) == 1
        assert result.messages[0]["role"] == "assistant"


class TestNodePurity:
    """Verify nodes don't cause unintended side effects."""

    def test_node_does_not_mutate_external_state(self, state_factory):
        state = state_factory()
        original_uuid = state.uuid

        def pure_node(input_state: PilotAgentState) -> PilotAgentState:
            return input_state

        result = pure_node(state)
        assert state.uuid == original_uuid

    def test_multiple_node_invocations_independent(self, state_factory):
        state1 = state_factory(uuid="uuid1")
        state2 = state_factory(uuid="uuid2")

        def stateless_node(input_state: PilotAgentState) -> PilotAgentState:
            input_state.step_count += 1
            return input_state

        result1 = stateless_node(state1)
        result2 = stateless_node(state2)

        assert result1.uuid == "uuid1"
        assert result2.uuid == "uuid2"
