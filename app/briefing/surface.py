"""Read-only day-start projection of the durable Daily Briefing artifact."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any, Literal, TypedDict

from app.briefing.compose import BriefingReadError, load_briefing
from app.vault.manager import VaultContext


class DayStartBriefing(TypedDict):
    state: Literal["pending", "unreadable", "degraded", "full"]
    date: str
    preview: str
    degraded_sections: list[str]
    sections: list[dict[str, Any]]
    read_only: bool
    reason: str | None


def collect_day_start_briefing(
    *, vault_context: VaultContext, for_date: date
) -> DayStartBriefing:
    """Project exactly one day's briefing without deriving or mutating source state."""

    try:
        note = load_briefing(vault_context=vault_context, for_date=for_date)
    except (BriefingReadError, ValueError):
        return _empty_projection(for_date, state="unreadable", reason="briefing_unreadable")
    if note is None:
        return _empty_projection(for_date, state="pending", reason="not_yet_generated")

    sections: list[dict[str, Any]] = []
    preview = ""
    for name, section in note.sections.items():
        items = [asdict(item) for item in section.items]
        sections.append(
            {
                "name": name,
                "status": section.status,
                "reason": section.reason,
                "items": items,
            }
        )
        if not preview and items:
            preview = _item_preview(items[0])
    if not preview:
        preview = "Your briefing is ready."
    state: Literal["degraded", "full"] = (
        "degraded" if note.degraded_sections else "full"
    )
    return {
        "state": state,
        "date": note.briefing_date.isoformat(),
        "preview": preview,
        "degraded_sections": list(note.degraded_sections),
        "sections": sections,
        "read_only": True,
        "reason": None,
    }


def _empty_projection(
    for_date: date,
    *,
    state: Literal["pending", "unreadable"],
    reason: str,
) -> DayStartBriefing:
    return {
        "state": state,
        "date": for_date.isoformat(),
        "preview": "",
        "degraded_sections": [],
        "sections": [],
        "read_only": True,
        "reason": reason,
    }


def _item_preview(item: dict[str, Any]) -> str:
    for key in ("summary", "title", "key", "object_id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Your briefing is ready."


__all__ = ["DayStartBriefing", "collect_day_start_briefing"]
