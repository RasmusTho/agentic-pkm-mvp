from __future__ import annotations

from pathlib import Path
from typing import Dict, List
from uuid import uuid4

from app.components.concurrency import EventDedupStore
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
from app.services.outbox import append_jsonl_outbox_event, derive_idempotency_key, payload_fingerprint
from app.objects import DomainObject, ObjectStore

from .parser import ParsedAction, ParsedPanel, find_panels, parse_panel

# In-process redelivery guard for panel.intent.created re-emission (#2881).
# `run_panel_intent_for_note` re-parses the note's AI-panel blocks on every
# `panel.scan.requested` dispatch; a redelivered scan of the SAME unchanged
# note previously re-emitted N fresh events (one per panel block) because
# each event's own `event_id` is random per construction. Keyed on
# `(note_uuid, panel_id, raw_block content)` -- `panel_id` is the block's
# stable positional identity from `find_panels` (`panel-1`, `panel-2`, ...)
# and `raw_block` is the deterministic substring of note text the block was
# parsed from, so the SAME observation (same note content, same block order)
# maps to the same key, while genuinely new/changed panel content (edited
# instruction/actions, a reordered or added block) gets its own key and is
# never swallowed.
_PANEL_INTENT_DEDUP = EventDedupStore()


def reset_panel_intent_dedup_store() -> None:
    """Test-only reset hook, mirroring `app.promotion.consumer.reset_promotion_dedup_store`."""
    _PANEL_INTENT_DEDUP.clear()


def _panel_intent_dedup_key(note_uuid: str, panel_id: str, raw_block: str | None) -> str:
    fingerprint = payload_fingerprint({"raw_block": raw_block or ""})
    return derive_idempotency_key("panel.intent.created", f"{note_uuid}:{panel_id}", fingerprint)


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
    return PanelIntentAction(
        id=action_id,
        option_id=action.option_id,
        label=action.label,
        checked=action.checked,
        mapping=mapping,
        proposal_pending=action.proposal_pending,
    )


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
            # Content-derived dedup (#2881): the handler side (executed-action
            # filtering in `execute_panel_intent`) is already idempotent and
            # untouched here -- only the notification/audit emission is gated,
            # so a redelivered scan of the SAME unchanged panel block appends
            # at most one panel.intent.created JSONL line, while a genuinely
            # new/changed block (edited instruction/actions) still emits.
            dedup_key = _panel_intent_dedup_key(note_uuid, block.panel_id, block.raw_block)
            if not _PANEL_INTENT_DEDUP.seen(dedup_key):
                append_jsonl_outbox_event(resolved_outbox, event, default_source="panel_agent")
    return events


__all__ = ["run_panel_intent_for_note"]
