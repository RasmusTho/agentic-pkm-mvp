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


def _normalize_context_dimensions(value: Any) -> Dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if "scope" not in value or "sphere_memberships" not in value:
        return None
    scope = value.get("scope")
    spheres = value.get("sphere_memberships")
    if scope is None or not isinstance(scope, str):
        return None
    if not isinstance(spheres, list):
        return None
    return {
        "scope": scope.strip() or "default",
        "sphere_memberships": [str(item) for item in spheres],
        "situated_identity": value.get("situated_identity", None),
    }


class OutboxEvent(BaseModel):
    """Canonical outbox event envelope."""

    model_config = ConfigDict(populate_by_name=True)

    event: str
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    source: str
    timestamp: str = Field(default_factory=_now_iso)
    payload: Dict[str, Any] = Field(default_factory=dict)
    context_dimensions: Dict[str, Any] | None = None
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
    context_dimensions: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    timestamp: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> OutboxEvent:
    resolved_payload = payload or {}
    resolved_context = _normalize_context_dimensions(context_dimensions)
    if resolved_context is None:
        resolved_context = _normalize_context_dimensions(resolved_payload.get("context_dimensions"))
    return OutboxEvent(
        event=event,
        trace_id=trace_id or uuid4().hex,
        source=source,
        timestamp=timestamp or _now_iso(),
        payload=resolved_payload,
        context_dimensions=resolved_context,
        meta=_build_meta(meta),
    )


__all__ = ["OutboxEvent", "make_outbox_event"]
