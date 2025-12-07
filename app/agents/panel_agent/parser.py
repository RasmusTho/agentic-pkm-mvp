from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal

from app.agents.panel.filters import is_ai_fence

_SECTION_MAP: dict[str, Literal["instruction", "actions", "log"]] = {
    "ai-instruktion": "instruction",
    "ai-åtgärder": "actions",
    "ai-logg": "log",
}
_ACTION_PATTERN = re.compile(r"^- \[( |x|X)\]\s*(.+)$")


@dataclass
class PanelBlock:
    panel_id: str
    raw_block: str


@dataclass
class ParsedAction:
    label: str
    checked: bool


@dataclass
class ParsedPanel:
    instruction: str
    actions: list[ParsedAction]
    panel_id: str | None = None
    raw_block: str | None = None


def find_panels(markdown: str) -> list[PanelBlock]:
    lines = markdown.splitlines()
    panels: list[PanelBlock] = []
    open_idx: int | None = None
    for idx, line in enumerate(lines):
        if is_ai_fence(line):
            if open_idx is None:
                open_idx = idx
            else:
                block = "\n".join(lines[open_idx : idx + 1])
                panels.append(PanelBlock(panel_id=f"panel-{len(panels) + 1}", raw_block=block))
                open_idx = None
    if panels:
        return panels

    if _looks_like_heading_panel(lines):
        return [PanelBlock(panel_id="panel-1", raw_block=markdown)]
    return []


def parse_panel(block: str, panel_id: str | None = None) -> ParsedPanel:
    lines = [line for line in block.splitlines() if not is_ai_fence(line)]
    sections = _collect_sections(lines)
    instruction = "\n".join(sections["instruction"]).strip()
    actions: list[ParsedAction] = []
    for raw in sections["actions"]:
        action = _parse_action(raw)
        if action:
            actions.append(action)
    return ParsedPanel(instruction=instruction, actions=actions, panel_id=panel_id, raw_block=block)


def _collect_sections(lines: Iterable[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"instruction": [], "actions": [], "log": []}
    current: Literal["instruction", "actions", "log"] | None = None
    for raw_line in lines:
        section = _match_section(raw_line)
        if section:
            current = section
            continue
        if raw_line.strip().startswith(("##", "###")):
            current = None
            continue
        if current:
            sections[current].append(raw_line.rstrip())
    return sections


def _match_section(line: str) -> Literal["instruction", "actions", "log"] | None:
    stripped = line.strip().lower()
    for heading, section in _SECTION_MAP.items():
        if stripped.startswith(f"## {heading}") or stripped.startswith(f"### {heading}"):
            return section  # type: ignore[return-value]
    return None


def _parse_action(line: str) -> ParsedAction | None:
    match = _ACTION_PATTERN.match(line.strip())
    if not match:
        return None
    checked = match.group(1).lower() == "x"
    label = match.group(2).strip()
    if not label:
        return None
    return ParsedAction(label=label, checked=checked)


def _looks_like_heading_panel(lines: list[str]) -> bool:
    found_instruction = False
    found_actions = False
    for line in lines:
        section = _match_section(line)
        if section == "instruction":
            found_instruction = True
        elif section == "actions":
            found_actions = True
    return found_instruction and found_actions


__all__ = [
    "find_panels",
    "parse_panel",
    "PanelBlock",
    "ParsedPanel",
    "ParsedAction",
]
