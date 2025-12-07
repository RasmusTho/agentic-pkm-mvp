from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Dict
from uuid import uuid4

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


class PanelActionMapping(BaseModel):
    id: str
    intent_type: str
    downstream_event: str
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


__all__ = [
    "PanelActionMapping",
    "PanelIntentAction",
    "PanelInfo",
    "NoteRef",
    "PanelIntentPayload",
    "PanelIntentEvent",
    "PanelEventSource",
]
