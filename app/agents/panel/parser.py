from __future__ import annotations

import re
from typing import Literal

from .schema import PanelAction, PanelLogEntry, PanelState

_PANEL_SECTION = {
    "instruction": "ai-instruktion",
    "actions": "ai-åtgärder",
    "logs": "ai-logg",
}

_ACTION_PATTERN = re.compile(r"^- \[( |x|X)\]\s*(.*)$")


def parse_panel(markdown: str) -> PanelState:
    sections = _collect_panel_sections(markdown)
    instruction_text = "\n".join(sections["instruction"]).strip()
    actions = []
    for line in sections["actions"]:
        action = _line_to_action(line)
        if action:
            actions.append(action)
    logs = [PanelLogEntry(raw=line.strip()) for line in sections["logs"] if line.strip().startswith("-")]
    return PanelState(
        instruction_text=instruction_text,
        actions=actions,
        logs=logs,
    )


def _collect_panel_sections(markdown: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {key: [] for key in _PANEL_SECTION}
    current: Literal["instruction", "actions", "logs"] | None = None
    for raw_line in markdown.splitlines():
        stripped = raw_line.strip()
        lowered = stripped.lower()
        matched_section = _match_section(lowered)
        if matched_section:
            current = matched_section
            continue
        if stripped.startswith("## ") and _is_non_panel_heading(lowered):
            current = None
            continue
        if current:
            sections[current].append(raw_line.rstrip())
    return sections


def _match_section(line: str) -> Literal["instruction", "actions", "logs"] | None:
    for key, heading in _PANEL_SECTION.items():
        if line.startswith(f"## {heading}"):
            return key  # type: ignore[return-value]
    return None


def _is_non_panel_heading(line: str) -> bool:
    if not line.startswith("## "):
        return False
    for heading in _PANEL_SECTION.values():
        if line.startswith(f"## {heading}"):
            return False
    return True


def _line_to_action(line: str) -> PanelAction | None:
    match = _ACTION_PATTERN.match(line.strip())
    if not match:
        return None
    checked = match.group(1).lower() == "x"
    text = match.group(2).strip()
    if not text:
        return None
    return PanelAction(checked=checked, text=text)
