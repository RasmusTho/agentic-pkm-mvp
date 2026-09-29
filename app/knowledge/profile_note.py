"""Shared parsing of the governed Profile Note's durable body boundary."""

from __future__ import annotations

import re

import yaml

from app.knowledge.profile_authority import (
    ProfileAuthorityConflict,
    ProfileAuthorityContractError,
)


PROFILE_PROPOSAL_START = "<!--mimer:profile-proposal-start id={proposal_id}-->"
PROFILE_PROPOSAL_END = "<!--mimer:profile-proposal-end id={proposal_id}-->"
PROFILE_PROPOSAL_MARKER_RE = re.compile(
    r"<!--mimer:profile-proposal-(start|end) id=([A-Za-z0-9][A-Za-z0-9._:-]*)-->"
)


def load_profile_note_frontmatter(note_text: str) -> tuple[dict[object, object], str]:
    """Parse frontmatter using delimiter lines, never substring splitting."""

    lines = note_text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return {}, note_text
    end = next(
        (index for index in range(1, len(lines)) if lines[index].rstrip("\r\n") == "---"),
        None,
    )
    if end is None:
        raise ProfileAuthorityContractError("Profile Note frontmatter is incomplete")
    try:
        frontmatter = yaml.safe_load("".join(lines[1:end])) or {}
    except yaml.YAMLError as exc:
        raise ProfileAuthorityContractError("Profile Note frontmatter is invalid") from exc
    if not isinstance(frontmatter, dict):
        raise ProfileAuthorityContractError("Profile Note frontmatter must be a mapping")
    return frontmatter, "".join(lines[end + 1 :]).lstrip("\n")


def split_profile_note_header(note_text: str) -> tuple[str, str]:
    """Return the stable header and remainder using line delimiters."""

    lines = note_text.splitlines(keepends=True)
    index = 0
    if lines and lines[0].rstrip("\r\n") == "---":
        index = 1
        while index < len(lines) and lines[index].rstrip("\r\n") != "---":
            index += 1
        if index >= len(lines):
            raise ProfileAuthorityContractError("Profile Note frontmatter is incomplete")
        index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines) or not lines[index].lstrip().startswith("# "):
        raise ProfileAuthorityContractError("Profile Note must have a top-level title")
    index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    header = "".join(lines[:index])
    return header, note_text[len(header) :]


def profile_note_parts(note_text: str) -> tuple[str, str, str]:
    """Return header, managed proposal panel, and approved body."""

    header, remainder = split_profile_note_header(note_text)
    panels = _find_panels(note_text)
    managed = [block for block in panels if "<!--mimer:profile-proposal-start id=" in block]
    if len(managed) > 1 or len(panels) != len(managed):
        raise ProfileAuthorityConflict("Profile Note contains an unrelated or ambiguous Panel")
    panel = ""
    body = remainder
    if managed:
        proposal_ids = PROFILE_PROPOSAL_MARKER_RE.findall(managed[0])
        starts = [proposal_id for kind, proposal_id in proposal_ids if kind == "start"]
        ends = [proposal_id for kind, proposal_id in proposal_ids if kind == "end"]
        if len(starts) != 1 or len(ends) != 1 or starts[0] != ends[0]:
            raise ProfileAuthorityContractError("Profile Note proposal panel is incomplete")
        panel_id = starts[0]
        panel, body = _extract_panel_span(remainder, panel_id)
        if not panel or panel.count(PROFILE_PROPOSAL_START.format(proposal_id=panel_id)) != 1:
            raise ProfileAuthorityContractError("Profile Note proposal panel is malformed")
    return header, panel, body.strip("\n")


def _extract_panel_span(remainder: str, proposal_id: str) -> tuple[str, str]:
    lines = remainder.splitlines(keepends=True)
    offsets: list[int] = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    marker_line = next(
        (
            index
            for index, line in enumerate(lines)
            if PROFILE_PROPOSAL_START.format(proposal_id=proposal_id) in line
        ),
        None,
    )
    if marker_line is None:
        return "", remainder
    start_line = next(
        (index for index in range(marker_line - 1, -1, -1) if _is_panel_fence(lines[index])),
        None,
    )
    end_line = next(
        (index for index in range(marker_line + 1, len(lines)) if _is_panel_fence(lines[index])),
        None,
    )
    if start_line is None or end_line is None:
        return "", remainder
    start_offset = offsets[start_line]
    end_offset = offsets[end_line] + len(lines[end_line])
    return remainder[start_offset:end_offset], remainder[:start_offset] + remainder[end_offset:]


def _is_panel_fence(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("%%") and "ai" in stripped.strip("%").lower()


def _find_panels(markdown: str) -> list[str]:
    """Recognize profile proposal panels without importing an agent runtime."""

    lines = markdown.splitlines()
    panels: list[str] = []
    open_index: int | None = None
    for index, line in enumerate(lines):
        if not _is_panel_fence(line):
            continue
        if open_index is None:
            open_index = index
        else:
            panels.append("\n".join(lines[open_index : index + 1]))
            open_index = None
    if panels:
        return panels
    lowered = [line.strip().lower() for line in lines]
    if any(line.startswith(("## ai-instruktion", "### ai-instruktion")) for line in lowered) and any(
        line.startswith(("## ai-åtgärder", "### ai-åtgärder")) for line in lowered
    ):
        return [markdown]
    return []


__all__ = [
    "PROFILE_PROPOSAL_END",
    "PROFILE_PROPOSAL_MARKER_RE",
    "PROFILE_PROPOSAL_START",
    "load_profile_note_frontmatter",
    "profile_note_parts",
    "split_profile_note_header",
]
