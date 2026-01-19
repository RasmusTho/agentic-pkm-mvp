from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Dict, Iterable, List

from pydantic import BaseModel, Field

from app.events.schema import OutboxEvent
from app.store.object_store import DomainObject, ObjectStore
from app.settings.panel_actions import PanelActionMapping

from .events import panel_intent_to_event
from .intents import PanelIntent, enrich_panel_intents
from .parser import parse_panel
from .schema import PanelState

_ACTION_PATTERN = re.compile(r"^(\s*-\s*\[( |x|X)\]\s*)(.*?)(\s*<!--\s*ai:id=([A-Za-z0-9_.-]+)\s*-->)?\s*$")
_AI_STATUS_HEADER = "> [!info]- AI status"
_MAX_RECEIPTS = 20
_EXECUTED_FALLBACK: dict[str, set[str]] = {}


class PanelAgentResult(BaseModel):
    state: PanelState
    intents: list[PanelIntent]
    updated_markdown: str
    events: list[OutboxEvent] = Field(default_factory=list)


def _stable_action_id(text: str) -> str:
    digest = hashlib.sha1(text.strip().encode("utf-8")).hexdigest()
    return digest[:8]


def _annotate_action_ids(markdown: str) -> str:
    lines = markdown.splitlines()
    changed = False
    for idx, line in enumerate(lines):
        match = _ACTION_PATTERN.match(line)
        if not match:
            continue
        label = (match.group(3) or "").strip()
        action_id = match.group(5)
        if action_id:
            continue
        action_id = _stable_action_id(label)
        prefix = match.group(1)
        lines[idx] = f"{prefix}{label} <!--ai:id={action_id}-->"
        changed = True
    if not changed:
        return markdown
    return "\n".join(lines)


def _parse_receipts(lines: list[str]) -> tuple[int | None, int | None, list[str]]:
    start = end = None
    receipts: list[str] = []
    for idx, line in enumerate(lines):
        if line.strip().lower().startswith(_AI_STATUS_HEADER.lower()):
            start = idx
            end = idx + 1
            j = idx + 1
            while j < len(lines) and lines[j].lstrip().startswith(">"):
                content = lines[j].lstrip()[1:].lstrip()
                if content.startswith("- "):
                    receipts.append(content[2:].strip())
                j += 1
                end = j
            break
    return start, end, receipts


def _write_receipts(markdown: str, new_receipts: list[str], *, clear: bool, preferred_index: int | None) -> str:
    lines = markdown.splitlines()
    start, end, receipts = _parse_receipts(lines)
    if start is None and not new_receipts and not clear:
        return markdown
    if start is None:
        start = end = preferred_index
    receipts = [] if clear else receipts
    receipts = receipts + new_receipts
    if len(receipts) > _MAX_RECEIPTS:
        receipts = receipts[-_MAX_RECEIPTS:]
    block = [_AI_STATUS_HEADER]
    block.extend([f"> - {line}" for line in receipts])
    if start is None or end is None:
        insert_at = len(lines)
        if preferred_index is not None:
            insert_at = min(max(preferred_index, 0), len(lines))
        lines.append("")
        lines[insert_at:insert_at] = block
    else:
        lines[start:end] = block
    return "\n".join(lines)


def _remove_actions_from_markdown(markdown: str, action_ids: set[str]) -> str:
    if not action_ids:
        return markdown
    result: list[str] = []
    for line in markdown.splitlines():
        match = _ACTION_PATTERN.match(line)
        if match:
            candidate_id = match.group(5)
            if candidate_id and candidate_id in action_ids:
                continue
        result.append(line)
    return "\n".join(result)


def _upsert_executed_ids(note_id: str, action_ids: Iterable[str]) -> None:
    new_ids = {aid for aid in action_ids if aid}
    if not new_ids:
        return
    store = ObjectStore()
    existing = store.get_object(note_id)
    payload = dict(existing.payload or {}) if existing else {}
    executed = set(payload.get("executed_action_ids") or [])
    executed |= new_ids
    payload["executed_action_ids"] = sorted(executed)
    try:
        if existing is None:
            obj = DomainObject(
                uuid=note_id,
                kind="note",
                payload=payload,
                source_ref=None,
                created_at=datetime.now(timezone.utc),
            )
        else:
            existing.payload = payload
            obj = existing
        store.save_object(obj, emit_outbox=False)
    except Exception:
        _EXECUTED_FALLBACK[note_id] = set(executed)
        return
    _EXECUTED_FALLBACK[note_id] = set(executed)


def handle_note_update(
    note_id: str,
    old_markdown: str,
    new_markdown: str,
    action_mappings: Dict[str, PanelActionMapping] | None = None,
    note_path: str | None = None,
) -> PanelAgentResult:
    annotated_markdown = _annotate_action_ids(new_markdown or "")
    old_state = parse_panel(old_markdown or "")
    new_state = parse_panel(annotated_markdown)
    mappings = dict(action_mappings or {})

    store = ObjectStore()
    stored = store.get_object(note_id)
    executed_ids = set(_EXECUTED_FALLBACK.get(note_id, set()))
    if stored:
        executed_ids |= set((stored.payload or {}).get("executed_action_ids") or [])

    intents: list[PanelIntent] = []
    receipts: list[str] = []
    executed_now: list[str] = []
    remove_ids: set[str] = set()
    if (old_state.instruction_text or "").strip() != (new_state.instruction_text or "").strip():
        intents.append(PanelIntent(kind="instruction_updated", instruction_text=new_state.instruction_text.strip()))
    for action in new_state.actions:
        if not action.checked or not action.text:
            continue
        action_id = action.action_id or _stable_action_id(action.text)
        if action_id in executed_ids:
            remove_ids.add(action_id)
            continue
        intents.append(PanelIntent(kind="action_triggered", action_text=action.text, action_id=action_id))
        receipts.append(f"✅ {action.text}")
        executed_now.append(action_id)

    # Freeform commands: clear status
    instruction_lower = (new_state.instruction_text or "").lower()
    clear_status = "clear status" in instruction_lower or "clear ai status" in instruction_lower

    def _resolve_promotion_mapping() -> PanelActionMapping | None:
        for key, mapping in mappings.items():
            if mapping.event_type == "promote.intent.created" or mapping.event_type.startswith("review.promote"):
                return mapping
            if mapping.action_id and mapping.action_id == "promote.evergreen":
                return mapping
            if key.lower() in {"gör denna anteckning evergreen", "make this note evergreen"}:
                return mapping
        return None

    auto_promote_id = "auto:promote.evergreen"
    if any(phrase in instruction_lower for phrase in ("promote this", "make evergreen", "make this note evergreen")):
        if auto_promote_id not in executed_ids:
            mapping = _resolve_promotion_mapping()
            if mapping is None:
                mapping = PanelActionMapping(
                    text="Make this note evergreen",
                    event_type="promote.intent.created",
                    payload_template={"maturity": "evergreen"},
                    action_id="promote.evergreen",
                )
                mappings[mapping.text] = mapping
            intents.append(
                PanelIntent(
                    kind="action_triggered",
                    action_text=mapping.text or "Make this note evergreen",
                    action_id=auto_promote_id,
                    event_type=mapping.event_type,
                )
            )
            receipts.append("✅ auto-executed: promote")
            executed_now.append(auto_promote_id)

    if mappings:
        intents = enrich_panel_intents(intents, mappings)

    note_payload = {"uuid": note_id}
    if note_path:
        note_payload["path"] = note_path

    events: list[OutboxEvent] = []
    if new_state.spans or new_state.actions or new_state.instruction_text:
        panel_payload = {
            "note": note_payload,
            "instruction": new_state.instruction_text,
            "actions": [
                {"id": action.action_id, "label": action.text, "checked": action.checked} for action in new_state.actions
            ],
        }
        events.append(OutboxEvent(event="panel.intent.created", source="panel.agent", payload=panel_payload))
        events.append(OutboxEvent(event="panel.intent.executed", source="panel.agent", payload=panel_payload))
    for intent in intents:
        event = panel_intent_to_event(
            intent,
            mappings,
            note_id=note_id,
            instruction_text=new_state.instruction_text,
            note_path=note_path,
        )
        if event is not None:
            events.append(event)
            if intent.kind == "action_triggered" and intent.event_type:
                events.append(
                    OutboxEvent(
                        event="panel.action.triggered",
                        source="panel.agent",
                        payload={
                            "note": note_payload,
                            "action": {"id": intent.action_id, "label": intent.action_text},
                            "target_event": event.event,
                        },
                    )
                )

    updated_markdown = annotated_markdown
    ids_to_remove = set(executed_now) | remove_ids
    if ids_to_remove:
        updated_markdown = _remove_actions_from_markdown(updated_markdown, ids_to_remove)

    preferred_index = None
    if new_state.spans:
        _, end = new_state.spans[-1]
        preferred_index = end + 1
    updated_markdown = _write_receipts(
        updated_markdown,
        [entry for entry in receipts],
        clear=clear_status,
        preferred_index=preferred_index,
    )

    _upsert_executed_ids(note_id, executed_now)

    return PanelAgentResult(state=new_state, intents=intents, updated_markdown=updated_markdown, events=events)


__all__ = ["handle_note_update", "PanelAgentResult"]
