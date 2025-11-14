from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentMessageBase(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    kind: Literal["request", "response", "error"]
    sender: str
    recipient: str
    correlation_id: str | None = None
    trace_id: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRequest(AgentMessageBase):
    kind: Literal["request"] = "request"
    intent: str | None = None


class AgentResponse(AgentMessageBase):
    kind: Literal["response"] = "response"
    status: Literal["ok", "partial", "error"] = "ok"


class AgentError(AgentMessageBase):
    kind: Literal["error"] = "error"
    error_type: str
    error_message: str


def _safe_dict(value: dict[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


def new_request(
    *,
    sender: str,
    recipient: str,
    intent: str | None = None,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> AgentRequest:
    return AgentRequest(
        sender=sender,
        recipient=recipient,
        intent=intent,
        payload=_safe_dict(payload),
        metadata=_safe_dict(metadata),
        correlation_id=correlation_id,
        trace_id=trace_id,
    )


def new_response(
    *,
    sender: str,
    recipient: str,
    status: Literal["ok", "partial", "error"] = "ok",
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> AgentResponse:
    return AgentResponse(
        sender=sender,
        recipient=recipient,
        status=status,
        payload=_safe_dict(payload),
        metadata=_safe_dict(metadata),
        correlation_id=correlation_id,
        trace_id=trace_id,
    )


def new_error(
    *,
    sender: str,
    recipient: str,
    error_type: str,
    error_message: str,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> AgentError:
    return AgentError(
        sender=sender,
        recipient=recipient,
        error_type=error_type,
        error_message=error_message,
        payload=_safe_dict(payload),
        metadata=_safe_dict(metadata),
        correlation_id=correlation_id,
        trace_id=trace_id,
    )


__all__ = [
    "AgentMessageBase",
    "AgentRequest",
    "AgentResponse",
    "AgentError",
    "new_request",
    "new_response",
    "new_error",
]
