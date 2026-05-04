from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.settings.runtime import get_settings_bundle


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_event_id() -> str:
    return uuid4().hex


def new_trace_id() -> str:
    return uuid4().hex


def _default_instance_id() -> str:
    try:
        bundle = get_settings_bundle()
        instance_id = getattr(getattr(bundle, "instance", None), "id", None)
        if instance_id:
            return str(instance_id)
    except Exception:
        pass
    return "home"


class Event(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event_type: str = Field(alias="event_type")
    event_id: str = Field(default_factory=new_event_id)
    trace_id: str | None = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    context_dimensions: Dict[str, Any] | None = None
    created_at: str = Field(default_factory=_now_iso)
    source: str | None = None
    instance_id: str = Field(default_factory=_default_instance_id)


def new_event(
    *,
    event_type: str,
    payload: Dict[str, Any] | None = None,
    context_dimensions: Dict[str, Any] | None = None,
    trace_id: str | None = None,
    source: str | None = None,
    event_id: str | None = None,
    created_at: str | None = None,
    instance_id: str | None = None,
) -> Event:
    data = dict(payload or {})
    event_kwargs: Dict[str, Any] = dict(
        event_type=event_type,
        event_id=event_id or new_event_id(),
        trace_id=trace_id,
        payload=data,
        context_dimensions=context_dimensions,
        created_at=created_at or _now_iso(),
        source=source,
    )
    if instance_id is not None:
        event_kwargs["instance_id"] = instance_id
    return Event(**event_kwargs)


__all__ = ["Event", "new_event", "new_event_id", "new_trace_id"]
