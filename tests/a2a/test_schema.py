from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.a2a.schema import AgentError, new_error, new_request, new_response


def test_agent_request_roundtrip_serializable() -> None:
    request = new_request(
        sender="Classifier",
        recipient="DeliberationAgent",
        intent="reason",
        payload={"topic": "delta"},
        metadata={"priority": "low"},
        trace_id="trace-1",
    )

    dumped = request.model_dump(mode="json")
    assert dumped["kind"] == "request"
    assert dumped["intent"] == "reason"
    json.dumps(dumped)  # raises if not serializable


def test_agent_response_defaults() -> None:
    response = new_response(sender="DeliberationAgent", recipient="Classifier")
    assert response.status == "ok"
    assert response.kind == "response"


def test_agent_error_requires_fields() -> None:
    with pytest.raises(ValidationError):
        AgentError(sender="Projector", recipient="Reviewer")  # type: ignore[arg-type]


def test_agent_error_factory_populates_fields() -> None:
    err = new_error(
        sender="Projector",
        recipient="Classifier",
        error_type="not_ready",
        error_message="Still indexing",
        payload={"stage": "chunk"},
    )
    assert err.kind == "error"
    assert err.payload["stage"] == "chunk"


def test_factories_preserve_correlation_and_trace_ids() -> None:
    request = new_request(
        sender="Classifier",
        recipient="Reviewer",
        intent="review",
        correlation_id="corr-1",
        trace_id="trace-1",
    )
    response = new_response(
        sender="Reviewer",
        recipient="Classifier",
        correlation_id="corr-1",
        trace_id="trace-1",
    )
    err = new_error(
        sender="Reviewer",
        recipient="Classifier",
        error_type="not_implemented",
        error_message="not wired",
        correlation_id="corr-1",
        trace_id="trace-1",
    )

    assert request.correlation_id == "corr-1"
    assert request.trace_id == "trace-1"
    assert response.correlation_id == "corr-1"
    assert response.trace_id == "trace-1"
    assert err.correlation_id == "corr-1"
    assert err.trace_id == "trace-1"
