from __future__ import annotations

import re
from typing import Dict

from pydantic import BaseModel, Field

from app.events.models import Event
from app.settings.panel_actions import PanelActionMapping

from .events import panel_intent_to_event
from .intents import PanelIntent, diff_panel_states, enrich_panel_intents
from .parser import parse_panel
from .schema import PanelState

_ACTION_PATTERN = re.compile(r"^- \[( |x|X)\]\s*(.*)$")


class PanelAgentResult(BaseModel):
    state: PanelState
    intents: list[PanelIntent]
    updated_markdown: str
    events: list[Event] = Field(default_factory=list)


def handle_note_update(
    note_id: str,
    old_markdown: str,
    new_markdown: str,
    action_mappings: Dict[str, PanelActionMapping] | None = None,
) -> PanelAgentResult:
    old_state = parse_panel(old_markdown or "")
    new_state = parse_panel(new_markdown or "")
    intents = diff_panel_states(old_state, new_state)
    mappings = action_mappings or {}
    if mappings:
        intents = enrich_panel_intents(intents, mappings)
    triggered_actions = [intent.action_text for intent in intents if intent.kind == "action_triggered" and intent.action_text]

    updated_markdown = new_markdown
    if triggered_actions:
        updated_markdown = _remove_actions_from_markdown(updated_markdown, triggered_actions)
        updated_markdown = _append_log_entries(updated_markdown, triggered_actions)

    events: list[Event] = []
    if mappings:
        for intent in intents:
            event = panel_intent_to_event(intent, mappings, note_id=note_id, instruction_text=new_state.instruction_text)
            if event is not None:
                events.append(event)

    return PanelAgentResult(state=new_state, intents=intents, updated_markdown=updated_markdown, events=events)


def _remove_actions_from_markdown(markdown: str, action_texts: list[str]) -> str:
    action_set = {text.strip() for text in action_texts if text}
    if not action_set:
        return markdown
    lines = markdown.splitlines()
    result: list[str] = []
    in_actions = False
    for line in lines:
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("## ai-åtgärder"):
            in_actions = True
            result.append(line)
            continue
        if stripped.startswith("## ") and not lowered.startswith("## ai-åtgärder"):
            in_actions = False
        if in_actions and _action_line_matches(line, action_set):
            continue
        result.append(line)
    return "\n".join(result)


def _action_line_matches(line: str, action_set: set[str]) -> bool:
    match = _ACTION_PATTERN.match(line.strip())
    if not match:
        return False
    text = match.group(2).strip()
    return text in action_set


def _append_log_entries(markdown: str, action_texts: list[str]) -> str:
    entry_lines = [f'- Action: "{text}"' for text in action_texts if text]
    if not entry_lines:
        return markdown
    lines = markdown.splitlines()
    section = _locate_section(lines, "ai-logg")
    if section is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("## AI-logg")
        lines.append("")
        lines.extend(entry_lines)
        return "\n".join(lines)

    start, end = section
    insert_at = end
    if insert_at > start + 1 and lines[insert_at - 1].strip():
        lines.insert(insert_at, "")
        insert_at += 1
    lines[insert_at:insert_at] = entry_lines
    return "\n".join(lines)


def _locate_section(lines: list[str], heading_slug: str) -> tuple[int, int] | None:
    heading = f"## {heading_slug}"
    start_idx = None
    for idx, line in enumerate(lines):
        if line.strip().lower().startswith(heading):
            start_idx = idx
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for idx in range(start_idx + 1, len(lines)):
        if lines[idx].strip().startswith("## "):
            end_idx = idx
            break
    return start_idx, end_idx
