from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from app.settings.runtime import get_settings_bundle


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _default_meta() -> Dict[str, Any]:
    return {"version": "1.0"}


def _instance_provenance() -> Dict[str, str] | None:
    try:
        bundle = get_settings_bundle()
        instance = getattr(bundle, "instance", None)
        if instance is None:
            return None
        return {
            "instance_id": str(getattr(instance, "id", "home")),
            "instance_role": str(getattr(instance, "role", "master")),
            "environment": str(getattr(instance, "environment", "prod")),
        }
    except Exception:
        return None


def _build_meta(meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    resolved = dict(meta or _default_meta())
    resolved.setdefault("version", "1.0")
    instance = _instance_provenance()
    if instance is not None:
        resolved["instance_provenance"] = instance
    return resolved


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
        meta=_build_meta(meta),
    )


__all__ = ["OutboxEvent", "make_outbox_event"]
