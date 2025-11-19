from __future__ import annotations

from typing import Dict, Iterable, List

from pydantic import BaseModel

from app.settings.panel_actions import PanelActionMapping

from .schema import PanelState


class PanelIntent(BaseModel):
    kind: str
    action_text: str | None = None
    instruction_text: str | None = None
    event_type: str | None = None


def diff_panel_states(old: PanelState, new: PanelState) -> list[PanelIntent]:
    intents: list[PanelIntent] = []

    old_actions = {action.text: action for action in old.actions}
    for action in new.actions:
        if action.checked:
            previous = old_actions.get(action.text)
            if previous is None or not previous.checked:
                intents.append(PanelIntent(kind="action_triggered", action_text=action.text))

    if (old.instruction_text or "").strip() != (new.instruction_text or "").strip():
        intents.append(PanelIntent(kind="instruction_updated", instruction_text=new.instruction_text.strip()))

    return intents


def resolve_action_event_type(intent: PanelIntent, mappings: Dict[str, PanelActionMapping]) -> str | None:
    if intent.kind != "action_triggered" or not intent.action_text:
        return None
    mapping = mappings.get(intent.action_text)
    if not mapping:
        return None
    return mapping.event_type


def enrich_panel_intents(intents: Iterable[PanelIntent], mappings: Dict[str, PanelActionMapping]) -> List[PanelIntent]:
    if not mappings:
        return list(intents)
    enriched: List[PanelIntent] = []
    for intent in intents:
        if intent.kind == "action_triggered" and intent.action_text:
            event_type = resolve_action_event_type(intent, mappings)
            if event_type:
                enriched.append(intent.model_copy(update={"event_type": event_type}))
                continue
        enriched.append(intent)
    return enriched
