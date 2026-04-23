from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


class PanelActionMapping(BaseModel):
    id: str
    intent_type: str
    downstream_event: str
    trust_verb: str | None = None
    params: Dict[str, Any] = Field(default_factory=dict)


class PanelIntentAction(BaseModel):
    id: str
    label: str
    checked: bool
    mapping: PanelActionMapping | None = None


class PanelInfo(BaseModel):
    panel_id: str
    instruction: str
    raw_block: str | None = None


class NoteRef(BaseModel):
    uuid: str
    path: str | None = None
    origin: str | None = None


class PanelIntentPayload(BaseModel):
    note: NoteRef
    panel: PanelInfo
    actions: list[PanelIntentAction] = Field(default_factory=list)


class PanelEventSource(BaseModel):
    component: str = "panel_agent"
    trigger: str = "cli"
    sot: str = "v5.0-step1"


class PanelIntentEvent(BaseModel):
    event: str = "panel.intent.created"
    version: str = "1.0"
    timestamp: str = Field(default_factory=_now_iso)
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    source: PanelEventSource = Field(default_factory=PanelEventSource)
    payload: PanelIntentPayload


class PanelRuntimeActionResult(BaseModel):
    id: str
    label: str
    checked: bool
    status: Literal["triggered", "logged", "skipped"]
    intent_type: str | None = None
    emitted_events: list[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)


class PanelIntentExecutedPayload(BaseModel):
    note: NoteRef
    panel: PanelInfo
    actions: list[PanelRuntimeActionResult] = Field(default_factory=list)
    executed_action_ids: list[str] = Field(default_factory=list)
    cognition_mode: str | None = None


class PanelIntentExecutedEvent(BaseModel):
    event: str = "panel.intent.executed"
    version: str = "1.0"
    timestamp: str = Field(default_factory=_now_iso)
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    source: PanelEventSource = Field(
        default_factory=lambda: PanelEventSource(trigger="runtime", component="panel_agent", sot="v5.0-runtime1")
    )
    payload: PanelIntentExecutedPayload


class PanelActionLoggedEvent(BaseModel):
    event: str = "panel.action.logged"
    version: str = "1.0"
    timestamp: str = Field(default_factory=_now_iso)
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    source: PanelEventSource = Field(
        default_factory=lambda: PanelEventSource(trigger="runtime", component="panel_agent", sot="v5.0-runtime1")
    )
    payload: Dict[str, Any] = Field(default_factory=dict)


class PanelLogEntry(BaseModel):
    timestamp: str = Field(default_factory=_now_iso)
    trace_id: str | None = None
    note: NoteRef
    panel_id: str
    summary: str
    actions: list[PanelRuntimeActionResult] = Field(default_factory=list)
    cognition_mode: str | None = None


class PanelLogEvent(BaseModel):
    event: str = "panel.log.created"
    version: str = "1.0"
    timestamp: str = Field(default_factory=_now_iso)
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    source: PanelEventSource = Field(
        default_factory=lambda: PanelEventSource(trigger="runtime", component="panel_agent", sot="v5.0-runtime1")
    )
    payload: PanelLogEntry


__all__ = [
    "PanelActionMapping",
    "PanelIntentAction",
    "PanelInfo",
    "NoteRef",
    "PanelIntentPayload",
    "PanelIntentEvent",
    "PanelEventSource",
    "PanelRuntimeActionResult",
    "PanelIntentExecutedEvent",
    "PanelIntentExecutedPayload",
    "PanelActionLoggedEvent",
    "PanelLogEntry",
    "PanelLogEvent",
]
