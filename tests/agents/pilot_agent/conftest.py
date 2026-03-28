"""Shared fixtures for pilot agent tests."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from unittest.mock import MagicMock

from app.components.reasoning.facade import ReasoningFacade, TelemetryRecord, ToolResult
from app.components.llm.router import LLMRouter


@dataclass
class PilotAgentState:
    """State contract for pilot promotion agent."""

    uuid: str
    trace_id: str
    budget: int
    step_count: int
    decision: str | None = None
    executed_actions: list[str] = field(default_factory=list)
    error: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.uuid, str):
            raise TypeError("uuid must be str")
        if not isinstance(self.trace_id, str):
            raise TypeError("trace_id must be str")
        if not isinstance(self.budget, int):
            raise TypeError("budget must be int")
        if not isinstance(self.step_count, int):
            raise TypeError("step_count must be int")
        if self.decision is not None and not isinstance(self.decision, str):
            raise TypeError("decision must be str | None")
        if not isinstance(self.executed_actions, list):
            raise TypeError("executed_actions must be list[str]")
        if not all(isinstance(action, str) for action in self.executed_actions):
            raise TypeError("executed_actions must contain only str values")
        if self.error is not None and not isinstance(self.error, str):
            raise TypeError("error must be str | None")
        if not isinstance(self.messages, list):
            raise TypeError("messages must be list[dict[str, Any]]")
        if not all(isinstance(message, dict) for message in self.messages):
            raise TypeError("messages must contain only dict values")


# Pytest may load this file as plain `conftest`, while tests import it via its package path.
# Alias the module identity so dataclass `isinstance` checks stay stable.
sys.modules.setdefault("tests.agents.pilot_agent.conftest", sys.modules[__name__])


@pytest.fixture
def state_factory() -> callable:
    """Factory to create valid pilot agent state."""

    def _make_state(**overrides) -> PilotAgentState:
        defaults = {
            "uuid": uuid4().hex,
            "trace_id": uuid4().hex,
            "budget": 100,
            "step_count": 0,
            "decision": None,
            "executed_actions": [],
            "error": None,
            "messages": [],
        }
        defaults.update(overrides)
        return PilotAgentState(**defaults)

    return _make_state


@pytest.fixture
def mock_reasoning_facade() -> MagicMock:
    """Mock ReasoningFacade that doesn't call real LLM."""
    mock = MagicMock(spec=ReasoningFacade)

    # Default mock responses
    mock.chat.return_value = "Mock chat response"
    mock.structured.return_value = {"decision": "promote", "reason": "meets criteria"}
    mock.tool_use.return_value = ToolResult(
        tool_name="apply_metadata",
        arguments={"key": "maturity", "value": "stable"},
        raw='{"tool": "apply_metadata", "arguments": {"key": "maturity", "value": "stable"}}',
    )
    mock.telemetry = []

    return mock


@pytest.fixture
def mock_llm_router() -> MagicMock:
    """Mock LLMRouter for routing logic."""
    mock = MagicMock(spec=LLMRouter)
    mock.route.return_value = MagicMock(
        model="gpt-4",
        provider="openai",
    )
    return mock


@pytest.fixture
def mock_store() -> MagicMock:
    """Mock object store for vault note access."""
    mock = MagicMock()
    mock.get_object.return_value = MagicMock(
        uuid="test-uuid",
        kind="note",
        payload={"title": "Test Note"},
    )
    return mock


@pytest.fixture
def mock_event_emitter() -> MagicMock:
    """Mock event emission for outbox events."""
    mock = MagicMock()
    mock.emit.return_value = None
    mock.emitted_events = []

    def _track_emit(event_type: str, payload: dict, trace_id: str | None = None):
        mock.emitted_events.append(
            {
                "event_type": event_type,
                "payload": payload,
                "trace_id": trace_id,
            }
        )

    mock.emit.side_effect = _track_emit
    return mock
