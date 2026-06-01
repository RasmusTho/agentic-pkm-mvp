from __future__ import annotations

from pydantic import BaseModel, Field


class PanelAction(BaseModel):
    checked: bool = False
    text: str
    action_id: str | None = None
    option_id: str | None = None
    proposal_pending: bool = False


class PanelLogEntry(BaseModel):
    raw: str


class PanelState(BaseModel):
    instruction_text: str = ""
    actions: list[PanelAction] = Field(default_factory=list)
    logs: list[PanelLogEntry] = Field(default_factory=list)
    spans: list[tuple[int, int]] = Field(
        default_factory=list, description="Line index spans (inclusive) that belong to panel blocks."
    )
    fenced: bool = Field(default=False, description="Whether AI comment fences were detected.")
