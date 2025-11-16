from __future__ import annotations

import logging
from typing import Any

from app.a2a.schema import AgentError, AgentMessageBase, AgentRequest, AgentResponse, new_request
from app.agents.base.audit import audit_log
from app.events.types import AGENT_ERROR_CREATED, AGENT_REQUEST_CREATED, AGENT_RESPONSE_CREATED

logger = logging.getLogger(__name__)


def _base_details(message: AgentMessageBase) -> dict[str, Any]:
    return {
        "message_id": str(message.id),
        "kind": message.kind,
        "sender": message.sender,
        "recipient": message.recipient,
        "correlation_id": message.correlation_id,
        "trace_id": message.trace_id,
        "created_at": message.created_at.isoformat(),
    }


def _emit(action: str, message: AgentMessageBase, *, object_id: str | None, extra: dict[str, Any] | None) -> None:
    details = _base_details(message)
    if extra:
        details.update(extra)
    try:
        audit_log(
            object_id=object_id,
            agent=message.sender,
            action=action,
            trace_id=message.trace_id,
            details=details,
        )
    except Exception:  # pragma: no cover - audit log already handles fallbacks, this is belt + suspenders
        logger.exception(
            "Failed to emit A2A audit event %s", action, extra={"a2a_action": action, "a2a_message_id": details["message_id"]}
        )


def emit_agent_request_event(message: AgentRequest, *, object_id: str | None = None) -> None:
    extra = {"intent": message.intent, "payload_size": len(message.payload or {})}
    _emit(AGENT_REQUEST_CREATED, message, object_id=object_id, extra=extra)


def emit_agent_response_event(message: AgentResponse, *, object_id: str | None = None) -> None:
    extra = {"status": message.status, "payload_size": len(message.payload or {})}
    _emit(AGENT_RESPONSE_CREATED, message, object_id=object_id, extra=extra)


def emit_agent_error_event(message: AgentError, *, object_id: str | None = None) -> None:
    extra = {
        "error_type": message.error_type,
        "error_message": message.error_message,
        "payload_size": len(message.payload or {}),
    }
    _emit(AGENT_ERROR_CREATED, message, object_id=object_id, extra=extra)


def send_agent_request(
    *,
    sender: str,
    recipient: str,
    intent: str | None = None,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    object_id: str | None = None,
) -> AgentRequest:
    request = new_request(
        sender=sender,
        recipient=recipient,
        intent=intent,
        payload=payload,
        metadata=metadata,
        correlation_id=correlation_id,
        trace_id=trace_id,
    )
    emit_agent_request_event(request, object_id=object_id)
    return request


__all__ = [
    "emit_agent_request_event",
    "emit_agent_response_event",
    "emit_agent_error_event",
    "send_agent_request",
]
