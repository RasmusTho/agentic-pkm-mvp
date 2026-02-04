from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping

AutoRunMode = str  # "manual" | "watcher" | "never"

_AI_PANEL_FENCE_RE = re.compile(r"%%[^%\n]*ai[^%\n]*%%", re.IGNORECASE)
_TRUE_VALUES = {"1", "true", "yes", "on"}

DEFAULT_PROACTIVE_ASSIST = True
DEFAULT_MAX_NOTE_BYTES = 1_000_000


def _extract_mode(frontmatter: Mapping[str, Any]) -> str | None:
    if "ai_panel_auto_run" in frontmatter:
        return str(frontmatter.get("ai_panel_auto_run") or "").strip().lower()
    ai_panel = frontmatter.get("ai_panel")
    if isinstance(ai_panel, Mapping):
        raw = ai_panel.get("auto_run")
        return str(raw or "").strip().lower()
    return None


def get_auto_run_mode(frontmatter: Mapping[str, Any]) -> AutoRunMode:
    """
    Returns explicit auto-run mode for AI panels on a note.
    Allowed values: "never", "manual" (default), "watcher".
    """
    mode = _extract_mode(frontmatter) or ""
    if mode in {"never", "manual", "watcher"}:
        return mode  # type: ignore[return-value]
    return "manual"


def contains_ai_panel_fence(markdown: str | None) -> bool:
    """Detects whether the markdown contains an AI fence that can trigger the watcher."""
    if not markdown:
        return False
    return bool(_AI_PANEL_FENCE_RE.search(markdown))


def _as_bool(value: str | None, *, fallback: bool) -> bool:
    if value is None:
        return fallback
    stripped = value.strip().lower()
    if stripped == "":
        return fallback
    return stripped in _TRUE_VALUES


def proactive_assist_enabled() -> bool:
    return _as_bool(os.getenv("PANEL_PROACTIVE_ASSIST"), fallback=DEFAULT_PROACTIVE_ASSIST)


def _excluded_by_path(note_path: Path) -> bool:
    parts = set(note_path.parts)
    if ".obsidian" in parts:
        return True
    lowered_parts = {p.lower() for p in parts}
    if "templates" in lowered_parts:
        return True
    return False


def _has_existing_panel(markdown: str | None) -> bool:
    if not markdown:
        return False
    # Quick conservative checks: AI fences or legacy section headings.
    if contains_ai_panel_fence(markdown):
        return True
    lowered = markdown.lower()
    if "## ai-instruktion" in lowered or "## ai-åtgärder" in lowered or "## ai-logg" in lowered:
        return True
    return False


def watcher_panel_candidate_for_path(note_path: Path, frontmatter: Mapping[str, Any], markdown: str | None) -> bool:
    """True when the watcher should consider this note for panel runtime.

    - Engage-on-request: any note with an AI fence (unless explicitly opted out).
    - Proactive assist: eligible notes without a panel may get one created with proposals only.
    """
    mode = _extract_mode(frontmatter)
    if mode == "never":
        return False

    if contains_ai_panel_fence(markdown):
        return True

    if not proactive_assist_enabled():
        return False

    if _excluded_by_path(note_path):
        return False

    if _has_existing_panel(markdown):
        return False

    try:
        if note_path.stat().st_size > DEFAULT_MAX_NOTE_BYTES:
            return False
    except Exception:
        return False

    return True


def watcher_panel_candidate(
    frontmatter: Mapping[str, Any], markdown: str | None
) -> bool:
    """True when the watcher should consider this note for panel runtime."""
    mode = _extract_mode(frontmatter)
    if mode == "never":
        return False
    return contains_ai_panel_fence(markdown)


def watcher_may_run_panel(frontmatter: Mapping[str, Any]) -> bool:
    """
    True when watcher-driven panel runtime is allowed for this note.
    Manual CLI runs are always allowed.
    """
    return get_auto_run_mode(frontmatter) == "watcher"


__all__ = [
    "get_auto_run_mode",
    "watcher_may_run_panel",
    "contains_ai_panel_fence",
    "watcher_panel_candidate",
    "watcher_panel_candidate_for_path",
    "proactive_assist_enabled",
]
