from __future__ import annotations

from app.a2a.schema import AgentRequest, new_request
from app.agents.base.loop import Agent


def test_base_agent_handle_request_emits_not_implemented(monkeypatch):
    captured: dict[str, AgentRequest] = {}

    def fake_emit(message, *, object_id=None):
        captured["message"] = message

    monkeypatch.setattr("app.agents.base.loop.emit_agent_error_event", fake_emit)

    agent = Agent()
    request = new_request(sender="Classifier", recipient="Agent")
    result = agent.handle_agent_request(request)

    assert result is None
    assert captured["message"].error_type == "not_implemented"
    assert captured["message"].recipient == "Classifier"
