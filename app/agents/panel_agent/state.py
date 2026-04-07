from __future__ import annotations

from pathlib import Path
from typing import Any, List

from pydantic import BaseModel, ConfigDict, Field

from app.agents.panel_agent.settings import DeciderMode
from app.components.settings.panel_actions_loader import PanelActionCatalog
from app.agents.panel_agent.intent import PanelActionIntent
from app.events.panel import (
    NoteRef,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelLogEntry,
    PanelRuntimeActionResult,
)


class PanelAgentState(BaseModel):
    """State container for PanelAgent LangGraph execution."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    trace_id: str | None = None
    note: NoteRef
    panel: PanelInfo
    actions: List[PanelIntentAction] = Field(default_factory=list)
    action_catalog: PanelActionCatalog | None = None
    action_wiring: dict[str, str] = Field(default_factory=dict)
    previous_logs: List[dict[str, Any]] = Field(default_factory=list)
    policy_flags: dict[str, Any] = Field(default_factory=dict)
    selected_action_ids: List[str] = Field(default_factory=list)
    selected_action_reasons: dict[str, str] = Field(default_factory=dict)
    decider_mode: DeciderMode = "llm"
    note_content: str | None = None
    panel_hints: List[dict[str, Any]] = Field(default_factory=list)
    executed_action_ids: List[str] = Field(default_factory=list)
    proposed_action_ids: List[str] = Field(default_factory=list)
    vault_root: Path | None = None

    # Runtime-populated fields
    intent_event: PanelIntentEvent | None = None
    action_results: List[PanelRuntimeActionResult] = Field(default_factory=list)
    emitted_events: List[Any] = Field(default_factory=list)
    log_entry: PanelLogEntry | None = None
    panel_action_intent: PanelActionIntent | None = None


__all__ = ["PanelAgentState"]
