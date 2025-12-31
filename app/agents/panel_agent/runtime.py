from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field

from app.agents.panel_agent.graph import run_panel_graph
from app.agents.panel_agent.intent import PanelActionIntent
from app.agents.panel_agent.planning import plan_panel_actions
from app.agents.panel_agent.settings import get_panel_agent_decider, get_panel_agent_pipeline
from app.agents.panel_agent.state import PanelAgentState
from app.agents.panel_agent.wiring import get_default_action_wiring, load_action_wiring
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
    wiring = get_default_action_wiring()
    store = ObjectStore()
    note_obj = store.get_object(intent_event.payload.note.uuid)
    note_text = ""
    executed_ids: set[str] = set()
    if note_obj:
        payload = note_obj.payload or {}
        note_text = str(payload.get("raw_text") or payload.get("text") or "")
        executed_ids = set(payload.get("executed_action_ids") or [])

    actions = [action for action in intent_event.payload.actions if action.id not in executed_ids]
    payload = intent_event.payload.model_copy(update={"actions": list(actions)})
    intent_event = intent_event.model_copy(update={"payload": payload})
    panel_hints = [
        {"id": action.id, "label": action.label, "checked": action.checked} for action in actions
    ]
    initial_state = PanelAgentState(
        trace_id=intent_event.trace_id,
        note=intent_event.payload.note,
        panel=intent_event.payload.panel,
        actions=list(actions),
        intent_event=intent_event,
        action_catalog=catalog,
        action_wiring=wiring,
        note_content=note_text,
        panel_hints=panel_hints,
        executed_action_ids=sorted(executed_ids),
    )
    decider_mode = get_panel_agent_decider()
    state = run_panel_graph(initial_state, decider_mode=decider_mode)

    pipeline_mode = get_panel_agent_pipeline()
    if pipeline_mode == "planner":
        triggered_ids = [a.id for a in state.action_results if a.checked and a.status == "triggered"]
        if triggered_ids:
            resolved_actions = [action for action in state.actions if action.id in triggered_ids]
            state.panel_action_intent = PanelActionIntent(
                note=intent_event.payload.note,
                instruction=intent_event.payload.panel.instruction,
                actions=triggered_ids,
                resolved_actions=resolved_actions,
                source="panel_agent",
            )
            plan_panel_actions(state.panel_action_intent, event_id=intent_event.event_id, trace_id=intent_event.trace_id)

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
