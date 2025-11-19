from __future__ import annotations

from pydantic import BaseModel, Field


class PanelAction(BaseModel):
    checked: bool = False
    text: str


class PanelLogEntry(BaseModel):
    raw: str


class PanelState(BaseModel):
    instruction_text: str = ""
    actions: list[PanelAction] = Field(default_factory=list)
    logs: list[PanelLogEntry] = Field(default_factory=list)
