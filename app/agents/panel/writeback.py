"""Shared panel writeback utilities for checkbox removal, receipts, and executed-ID tracking.

Used by both the legacy ``handle_note_update`` path (``panel/agent.py``) and the
runtime/watcher ``execute_panel_intent`` path (``panel_agent/runtime.py``).
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

from app.store.object_store import DomainObject, ObjectStore

ACTION_PATTERN = re.compile(
    r"^(\s*-\s*\[( |x|X)\]\s*)(.*?)"
    r"(\s*<!--\s*ai:id=([A-Za-z0-9_.-]+)\s*-->)?"
    r"(\s*<!--\s*ai:proposed=([A-Za-z0-9_.-]+)\s*-->)?\s*$"
)
AI_STATUS_HEADER = "> [!info]- AI status"
MAX_RECEIPTS = 20

# In-memory fallback when ObjectStore writes fail.
EXECUTED_FALLBACK: dict[str, set[str]] = {}


def stable_action_id(text: str) -> str:
    """Deterministic short hash for a checkbox label."""
    digest = hashlib.sha1(text.strip().encode("utf-8")).hexdigest()
    return digest[:8]


def annotate_action_ids(markdown: str) -> str:
    """Ensure every checkbox line has an ``<!--ai:id=...-->`` annotation."""
    lines = markdown.splitlines()
    changed = False
    for idx, line in enumerate(lines):
        match = ACTION_PATTERN.match(line)
        if not match:
            continue
        label = (match.group(3) or "").strip()
        action_id = match.group(5)
        proposed_marker = match.group(6) or ""
        if action_id:
            continue
        action_id = stable_action_id(label)
        prefix = match.group(1)
        lines[idx] = f"{prefix}{label} <!--ai:id={action_id}-->{proposed_marker}"
        changed = True
    if not changed:
        return markdown
    return "\n".join(lines)


def _parse_receipts(lines: list[str]) -> tuple[int | None, int | None, list[str]]:
    start = end = None
    receipts: list[str] = []
    for idx, line in enumerate(lines):
        if line.strip().lower().startswith(AI_STATUS_HEADER.lower()):
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


def write_receipts(
    markdown: str,
    new_receipts: list[str],
    *,
    clear: bool = False,
    preferred_index: int | None = None,
) -> str:
    """Append receipt lines to the AI status callout, creating it if absent."""
    lines = markdown.splitlines()
    start, end, receipts = _parse_receipts(lines)
    if start is None and not new_receipts and not clear:
        return markdown
    if start is None:
        start = end = preferred_index
    receipts = [] if clear else receipts
    receipts = receipts + new_receipts
    if len(receipts) > MAX_RECEIPTS:
        receipts = receipts[-MAX_RECEIPTS:]
    block = [AI_STATUS_HEADER]
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


def remove_actions_from_markdown(markdown: str, action_ids: set[str]) -> str:
    """Remove checkbox lines whose ``ai:id`` annotation is in *action_ids*."""
    if not action_ids:
        return markdown
    result: list[str] = []
    for line in markdown.splitlines():
        match = ACTION_PATTERN.match(line)
        if match:
            candidate_id = match.group(5)
            if candidate_id and candidate_id in action_ids:
                continue
        result.append(line)
    return "\n".join(result)


def upsert_executed_ids(note_id: str, action_ids: Iterable[str]) -> None:
    """Persist *action_ids* into the ObjectStore ``executed_action_ids`` list."""
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
            from datetime import datetime, timezone

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
        EXECUTED_FALLBACK[note_id] = set(executed)
        return
    EXECUTED_FALLBACK[note_id] = set(executed)


__all__ = [
    "ACTION_PATTERN",
    "AI_STATUS_HEADER",
    "EXECUTED_FALLBACK",
    "MAX_RECEIPTS",
    "annotate_action_ids",
    "remove_actions_from_markdown",
    "stable_action_id",
    "upsert_executed_ids",
    "write_receipts",
]
