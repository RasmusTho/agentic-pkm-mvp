"""Regression tests for the pilot agent reasoning node."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.agents.pilot_agent.nodes.reason import reason_node


def test_reason_node_uses_reasoning_facade(state_factory, monkeypatch):
    state = state_factory()
    facade = MagicMock()
    facade.structured.return_value = {
        "decision": "promote",
        "reasoning": "meets criteria",
        "confidence": 0.91,
    }
    monkeypatch.setattr(
        "app.agents.pilot_agent.nodes.reason.get_reasoning_facade",
        lambda: facade,
    )

    result = reason_node(state)

    facade.structured.assert_called_once()
    assert result.decision == "promote"
    assert result.reason == "meets criteria"
    assert result.confidence == 0.91
    assert result.executed_actions[-1] == "reason"
