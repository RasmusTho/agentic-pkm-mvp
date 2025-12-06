from __future__ import annotations

from typing import Dict, Optional

from app.events.schema import OutboxEvent, make_outbox_event
from app.settings.panel_actions import PanelActionMapping

from .intents import PanelIntent, resolve_action_event_type

_PANEL_EVENT_SOURCE = "panel.agent"


def panel_intent_to_event(
    intent: PanelIntent,
    mappings: Dict[str, PanelActionMapping],
    *,
    note_id: str,
    instruction_text: str | None = None,
) -> Optional[OutboxEvent]:
    if intent.kind != "action_triggered" or not intent.action_text:
        return None

    mapping = mappings.get(intent.action_text)
    event_type = intent.event_type or (mapping.event_type if mapping else resolve_action_event_type(intent, mappings))
    if not event_type:
        return None

    payload = {}
    if mapping and mapping.payload_template:
        payload.update(mapping.payload_template)
    payload.update(
        {
            "note_id": note_id,
            "action_text": intent.action_text,
        }
    )
    if instruction_text:
        payload["instruction_text"] = instruction_text

    return make_outbox_event(event_type, source=_PANEL_EVENT_SOURCE, payload=payload)
