from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field

from app.agents.panel_agent.graph import run_panel_graph
from app.agents.panel_agent.settings import get_panel_agent_decider
from app.agents.panel_agent.state import PanelAgentState
from app.components.settings.panel_actions_loader import load_panel_action_catalog
from app.events.panel import NoteRef, PanelIntentEvent, PanelLogEntry, PanelRuntimeActionResult
from app.outbox.events import INDEX_OUTBOX_PATH
from app.store.object_store import ObjectStore


def _resolve_outbox_path(path: Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    env_path = os.getenv("INDEX_OUTBOX_PATH")
    if env_path:
        return Path(env_path)
    return Path(INDEX_OUTBOX_PATH)


def _write_outbox_events(outbox_path: Path, events: Iterable[Any]) -> None:
    outbox_path.parent.mkdir(parents=True, exist_ok=True)
    with outbox_path.open("a", encoding="utf-8") as handle:
        for event in events:
            if hasattr(event, "model_dump"):
                payload = event.model_dump(mode="json")
            elif isinstance(event, dict):
                payload = dict(event)
            else:
                continue
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
def _persist_log(note: NoteRef, log_entry: PanelLogEntry) -> None:
    store = ObjectStore()
    existing = store.get_object(note.uuid)
    if existing is None:
        return
    payload = dict(existing.payload or {})
    logs = list(payload.get("panel_logs") or [])
    logs.append(log_entry.model_dump(mode="json"))
    payload["panel_logs"] = logs
    existing.payload = payload
    store.save_object(existing, emit_outbox=False, trace_id=log_entry.trace_id)


class PanelRuntimeResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    intent: PanelIntentEvent
    actions: list[PanelRuntimeActionResult] = Field(default_factory=list)
    emitted_events: list[Any] = Field(default_factory=list)
    log_entry: PanelLogEntry | None = None


def execute_panel_intent(intent_event: PanelIntentEvent, *, outbox_path: Path | None = None) -> PanelRuntimeResult:
    resolved_outbox = _resolve_outbox_path(outbox_path)
    catalog = load_panel_action_catalog()
    store = ObjectStore()
    note_obj = store.get_object(intent_event.payload.note.uuid)
    note_text = ""
    if note_obj:
        payload = note_obj.payload or {}
        note_text = str(payload.get("raw_text") or payload.get("text") or "")
    panel_hints = [
        {"id": action.id, "label": action.label, "checked": action.checked} for action in intent_event.payload.actions
    ]
    initial_state = PanelAgentState(
        trace_id=intent_event.trace_id,
        note=intent_event.payload.note,
        panel=intent_event.payload.panel,
        actions=list(intent_event.payload.actions),
        intent_event=intent_event,
        action_catalog=catalog,
        note_content=note_text,
        panel_hints=panel_hints,
    )
    decider_mode = get_panel_agent_decider()
    state = run_panel_graph(initial_state, decider_mode=decider_mode)

    emitted_events = list(state.emitted_events or [])
    _write_outbox_events(resolved_outbox, emitted_events)
    if state.log_entry:
        _persist_log(intent_event.payload.note, state.log_entry)

    return PanelRuntimeResult(
        intent=intent_event,
        actions=state.action_results,
        emitted_events=emitted_events,
        log_entry=state.log_entry,
    )


__all__ = ["execute_panel_intent", "PanelRuntimeResult"]
