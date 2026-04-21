from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _default_meta() -> Dict[str, Any]:
    return {"version": "1.0"}


class OutboxEvent(BaseModel):
    """Canonical outbox event envelope."""

    model_config = ConfigDict(populate_by_name=True)

    event: str
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    source: str
    timestamp: str = Field(default_factory=_now_iso)
    payload: Dict[str, Any] = Field(default_factory=dict)
    meta: Dict[str, Any] = Field(default_factory=_default_meta)

    @property
    def event_type(self) -> str:
        # Backwards-compatible alias for consumers expecting `event_type`.
        return self.event


def make_outbox_event(
    event: str,
    *,
    source: str,
    payload: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    timestamp: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> OutboxEvent:
    return OutboxEvent(
        event=event,
        trace_id=trace_id or uuid4().hex,
        source=source,
        timestamp=timestamp or _now_iso(),
        payload=payload or {},
        meta=meta or _default_meta(),
    )


__all__ = ["OutboxEvent", "make_outbox_event"]
