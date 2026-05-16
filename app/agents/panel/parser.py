from __future__ import annotations

import re
from typing import Iterable, Literal

from .schema import PanelAction, PanelLogEntry, PanelState

_PANEL_SECTION = {
    "instruction": "ai-instruktion",
    "actions": "ai-åtgärder",
    "logs": "ai-logg",
}

_LABEL_PREFIXES = {
    "instruction": ("instruction", "instruktion"),
    "actions": ("actions", "åtgärder"),
    "logs": ("log", "logg"),
}
_ACTION_PATTERN = re.compile(
    r"^- \[( |x|X)\]\s*(.*?)"
    r"(?:\s*<!--\s*ai:id=([A-Za-z0-9_.-]+)\s*-->)?"
    r"(?:\s*<!--\s*ai:proposed=([A-Za-z0-9_.-]+)\s*-->)?\s*$"
)


def parse_panel(markdown: str) -> PanelState:
    lines = markdown.splitlines()
    fenced_spans = _find_fenced_spans(lines)
    spans = list(fenced_spans)
    fenced = bool(fenced_spans)
    has_panel = bool(fenced_spans)

    panel_lines: list[str]
    if fenced_spans:
        panel_lines = []
        for start, end in fenced_spans:
            content = lines[start + 1 : end] if end > start else []
            panel_lines.extend(content)
        sections = _collect_panel_sections_from_lines(panel_lines)
    else:
        sections = _collect_panel_sections_from_lines(lines)
        legacy_spans = _legacy_heading_spans(lines)
        spans = legacy_spans
        panel_lines = lines
        has_panel = has_panel or bool(legacy_spans)

    instruction_text = "\n".join(sections["instruction"]).strip()
    if not instruction_text and has_panel:
        instruction_text = _fallback_instruction(panel_lines).strip()
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
        spans=spans,
        fenced=fenced,
    )


def _collect_panel_sections_from_lines(lines: Iterable[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {key: [] for key in _PANEL_SECTION}
    current: Literal["instruction", "actions", "logs"] | None = None
    for raw_line in lines:
        stripped = raw_line.strip()
        lowered = stripped.lower()
        matched_section = _match_section(lowered)
        if matched_section:
            current = matched_section
            continue
        label_match = _match_label_section(stripped)
        if label_match:
            current = label_match
            content = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
            if content:
                sections[current].append(content)
            continue
        if stripped.startswith("## ") and _is_non_panel_heading(lowered):
            current = None
            continue
        if _ACTION_PATTERN.match(stripped):
            sections["actions"].append(raw_line.rstrip())
            continue
        if current:
            sections[current].append(raw_line.rstrip())

    if not sections["actions"]:
        for raw_line in lines:
            stripped = raw_line.strip()
            if _ACTION_PATTERN.match(stripped):
                sections["actions"].append(raw_line.rstrip())
    return sections


def _find_fenced_spans(lines: list[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    open_idx: int | None = None
    for idx, raw in enumerate(lines):
        if is_ai_fence(raw):
            if open_idx is None:
                open_idx = idx
            else:
                spans.append((open_idx, idx))
                open_idx = None
    return spans


def _legacy_heading_spans(lines: list[str]) -> list[tuple[int, int]]:
    start: int | None = None
    end: int | None = None
    current = False
    for idx, raw in enumerate(lines):
        lowered = raw.strip().lower()
        if _match_section(lowered):
            current = True
            if start is None:
                start = idx
            end = idx
            continue
        if current:
            if lowered.startswith("## ") and _is_non_panel_heading(lowered):
                end = idx - 1
                break
            if lowered == "" and idx + 1 < len(lines):
                nxt = lines[idx + 1].strip().lower()
                if not _match_section(nxt) and not nxt.startswith("## ") and nxt != "":
                    end = idx
                    break
            end = idx
    if start is None:
        return []
    if end is None:
        end = len(lines) - 1
    return [(start, max(start, end))]


def _match_section(line: str) -> Literal["instruction", "actions", "logs"] | None:
    for key, heading in _PANEL_SECTION.items():
        if line.startswith(f"## {heading}"):
            return key  # type: ignore[return-value]
    return None


def _match_label_section(line: str) -> Literal["instruction", "actions", "logs"] | None:
    lowered = line.lower()
    for key, labels in _LABEL_PREFIXES.items():
        for label in labels:
            if lowered.startswith(f"{label}:"):
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
    action_id = match.group(3) or None
    proposal_pending = match.group(4) is not None
    if not text:
        return None
    return PanelAction(
        checked=checked,
        text=text,
        action_id=action_id,
        proposal_pending=proposal_pending,
    )


def is_ai_fence(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("%%"):
        return False
    inner = stripped.strip("%").lower()
    return "ai" in inner


def _fallback_instruction(lines: list[str]) -> str:
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or is_ai_fence(stripped):
            continue
        if _match_section(stripped.lower()) or _match_label_section(stripped):
            # If the label line had inline content it would have been captured; skip the label itself
            if ":" in stripped:
                remainder = stripped.split(":", 1)[1].strip()
                if remainder:
                    return remainder
            continue
        if _ACTION_PATTERN.match(stripped):
            continue
        if stripped.startswith("## ") and _is_non_panel_heading(stripped.lower()):
            continue
        return stripped
    return ""
