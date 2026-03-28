"""Test suite for pilot agent state contract.

Enforces that agent state is properly structured, serializable, and validates correctly.
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields

import pytest

from tests.agents.pilot_agent.conftest import PilotAgentState


class TestPilotAgentStateStructure:
    """Verify state dataclass has all required fields."""

    def test_state_has_uuid_field(self, state_factory):
        state = state_factory()
        assert hasattr(state, "uuid")
        assert isinstance(state.uuid, str)

    def test_state_has_trace_id_field(self, state_factory):
        state = state_factory()
        assert hasattr(state, "trace_id")
        assert isinstance(state.trace_id, str)

    def test_state_has_budget_field(self, state_factory):
        state = state_factory()
        assert hasattr(state, "budget")
        assert isinstance(state.budget, int)

    def test_state_has_step_count_field(self, state_factory):
        state = state_factory()
        assert hasattr(state, "step_count")
        assert isinstance(state.step_count, int)

    def test_state_has_decision_field(self, state_factory):
        state = state_factory()
        assert hasattr(state, "decision")
        assert state.decision is None or isinstance(state.decision, str)

    def test_state_has_executed_actions_field(self, state_factory):
        state = state_factory()
        assert hasattr(state, "executed_actions")
        assert isinstance(state.executed_actions, list)

    def test_state_has_error_field(self, state_factory):
        state = state_factory()
        assert hasattr(state, "error")
        assert state.error is None or isinstance(state.error, str)


class TestPilotAgentStateSerialization:
    """Verify state can be serialized to JSON and round-tripped."""

    def test_state_serializes_to_json(self, state_factory):
        state = state_factory()
        state_dict = asdict(state)
        json_str = json.dumps(state_dict)
        assert json_str is not None
        assert isinstance(json_str, str)

    def test_state_json_round_trip(self, state_factory):
        original = state_factory(decision="promote", step_count=5)
        state_dict = asdict(original)
        json_str = json.dumps(state_dict)
        loaded_dict = json.loads(json_str)
        restored = PilotAgentState(**loaded_dict)
        assert restored.uuid == original.uuid
        assert restored.trace_id == original.trace_id
        assert restored.decision == original.decision
        assert restored.step_count == original.step_count

    def test_state_with_messages_serializes(self, state_factory):
        state = state_factory(
            messages=[
                {"role": "user", "content": "Test message"},
                {"role": "assistant", "content": "Response"},
            ]
        )
        state_dict = asdict(state)
        json_str = json.dumps(state_dict)
        assert len(json.loads(json_str)["messages"]) == 2

    def test_state_with_executed_actions_serializes(self, state_factory):
        state = state_factory(executed_actions=["validate", "analyze", "promote"])
        state_dict = asdict(state)
        json_str = json.dumps(state_dict)
        loaded = json.loads(json_str)
        assert loaded["executed_actions"] == ["validate", "analyze", "promote"]


class TestPilotAgentStateValidation:
    """Verify state validation enforces type correctness."""

    def test_state_requires_uuid(self):
        with pytest.raises(TypeError):
            PilotAgentState(
                trace_id="abc",
                budget=100,
                step_count=0,
            )

    def test_state_requires_trace_id(self):
        with pytest.raises(TypeError):
            PilotAgentState(
                uuid="abc",
                budget=100,
                step_count=0,
            )

    def test_state_budget_must_be_int(self, state_factory):
        with pytest.raises(TypeError):
            PilotAgentState(
                uuid="abc",
                trace_id="def",
                budget="100",
                step_count=0,
            )

    def test_state_step_count_must_be_int(self, state_factory):
        with pytest.raises(TypeError):
            PilotAgentState(
                uuid="abc",
                trace_id="def",
                budget=100,
                step_count="0",
            )

    def test_state_optional_fields_default_correctly(self, state_factory):
        state = state_factory()
        assert state.decision is None
        assert state.error is None
        assert state.executed_actions == []
        assert state.messages == []

    def test_state_all_fields_present(self):
        state = PilotAgentState(
            uuid="test",
            trace_id="trace",
            budget=100,
            step_count=0,
        )
        required_fields = {"uuid", "trace_id", "budget", "step_count", "decision", "executed_actions", "error", "messages"}
        state_fields = {f.name for f in fields(state)}
        assert required_fields.issubset(state_fields)
