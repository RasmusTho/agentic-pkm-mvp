from __future__ import annotations

from collections import deque

from app.a2a.events import (
    emit_agent_error_event,
    emit_agent_request_event,
    emit_agent_response_event,
    send_agent_request,
)
from app.a2a.schema import new_error, new_request, new_response


class AuditRecorder:
    def __init__(self) -> None:
        self.records: deque[dict] = deque()

    def __call__(self, **kwargs):
        self.records.append(kwargs)


def test_emit_agent_request_event(monkeypatch) -> None:
    recorder = AuditRecorder()
    monkeypatch.setattr("app.a2a.events.audit_log", recorder)

    message = new_request(sender="Classifier", recipient="Reasoner", intent="reason")
    emit_agent_request_event(message, object_id="obj-1")

    record = recorder.records.pop()
    assert record["action"] == "agent.request.created"
    assert record["details"]["sender"] == "Classifier"
    assert record["details"]["intent"] == "reason"


def test_emit_agent_response_and_error_events(monkeypatch) -> None:
    recorder = AuditRecorder()
    monkeypatch.setattr("app.a2a.events.audit_log", recorder)

    response = new_response(sender="Reasoner", recipient="Classifier", status="ok")
    emit_agent_response_event(response)
    error = new_error(
        sender="Reasoner",
        recipient="Classifier",
        error_type="failed",
        error_message="no context",
    )
    emit_agent_error_event(error)

    response_record = recorder.records.popleft()
    error_record = recorder.records.popleft()

    assert response_record["action"] == "agent.response.created"
    assert response_record["details"]["status"] == "ok"
    assert error_record["action"] == "agent.error.created"
    assert error_record["details"]["error_type"] == "failed"


def test_send_agent_request_returns_message_and_logs(monkeypatch) -> None:
    recorder = AuditRecorder()
    monkeypatch.setattr("app.a2a.events.audit_log", recorder)

    message = send_agent_request(sender="Projector", recipient="Reviewer", intent="package", object_id="obj-9")

    assert message.intent == "package"
    record = recorder.records.pop()
    assert record["object_id"] == "obj-9"
    assert record["details"]["message_id"] == str(message.id)
