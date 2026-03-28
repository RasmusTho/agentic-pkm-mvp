from __future__ import annotations

from pathlib import Path
from typing import Dict, List
from uuid import uuid4

from app.components.settings.panel_actions_loader import (
    PanelActionCatalog,
    load_panel_action_catalog,
    normalize_label,
)
from app.events.panel import (
    NoteRef,
    PanelEventSource,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
)
from app.outbox.events import INDEX_OUTBOX_PATH
from app.services.outbox import append_jsonl_outbox_event
from app.store.object_store import DomainObject, ObjectStore

from .parser import ParsedAction, ParsedPanel, find_panels, parse_panel


def _read_note_from_store(note_uuid: str) -> DomainObject:
    store = ObjectStore()
    domain_obj = store.get_object(note_uuid)
    if domain_obj is None:
        raise FileNotFoundError(f"Note not found in ObjectStore: {note_uuid}")
    return domain_obj


def _resolve_note_text(domain_obj: DomainObject) -> str:
    payload = domain_obj.payload or {}
    return str(payload.get("raw_text") or payload.get("text") or "")


def _note_ref(domain_obj: DomainObject) -> NoteRef:
    payload = domain_obj.payload or {}
    return NoteRef(
        uuid=str(domain_obj.uuid),
        path=str(domain_obj.source_ref) if domain_obj.source_ref else None,
        origin=str(payload.get("origin")) if payload.get("origin") else None,
    )


def _map_action(action: ParsedAction, catalog: PanelActionCatalog) -> PanelIntentAction:
    descriptor = catalog.find_by_label(action.label)
    mapping = descriptor.to_mapping() if descriptor else None
    action_id = descriptor.id if descriptor else (action.action_id or normalize_label(action.label) or uuid4().hex)
    return PanelIntentAction(id=action_id, label=action.label, checked=action.checked, mapping=mapping)


def _panel_payload(
    parsed: ParsedPanel,
    *,
    panel_id: str,
    note: NoteRef,
    catalog: PanelActionCatalog,
) -> PanelIntentPayload:
    actions = [_map_action(action, catalog) for action in parsed.actions]
    panel = PanelInfo(panel_id=panel_id, instruction=parsed.instruction, raw_block=parsed.raw_block)
    return PanelIntentPayload(note=note, panel=panel, actions=actions)
def run_panel_intent_for_note(
    note_uuid: str,
    trace_id: str | None = None,
    *,
    trigger: str = "cli",
    write_outbox: bool = True,
    outbox_path: Path | None = None,
) -> List[PanelIntentEvent]:
    """
    Load a note from ObjectStore by UUID, find AI panels, parse them,
    map actions via panel-actions settings, emit panel.intent.created events
    to the Outbox, and return the event objects (for testing).
    """
    domain_obj = _read_note_from_store(note_uuid)
    note_text = _resolve_note_text(domain_obj)
    note = _note_ref(domain_obj)
    catalog = load_panel_action_catalog()

    resolved_trace_id = trace_id or uuid4().hex
    events: list[PanelIntentEvent] = []
    resolved_outbox = Path(outbox_path) if outbox_path is not None else Path(INDEX_OUTBOX_PATH)
    for block in find_panels(note_text):
        parsed = parse_panel(block.raw_block, panel_id=block.panel_id)
        payload = _panel_payload(parsed, panel_id=block.panel_id, note=note, catalog=catalog)
        event = PanelIntentEvent(
            payload=payload,
            trace_id=resolved_trace_id,
            source=PanelEventSource(trigger=trigger, component="panel_agent", sot="v5.0-step1"),
        )
        events.append(event)
        if write_outbox:
            append_jsonl_outbox_event(resolved_outbox, event, default_source="panel_agent")
    return events


__all__ = ["run_panel_intent_for_note"]
