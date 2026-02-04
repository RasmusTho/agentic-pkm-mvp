from __future__ import annotations

import re
from typing import Any, Mapping

AutoRunMode = str  # "manual" | "watcher" | "never"

_AI_PANEL_FENCE_RE = re.compile(r"%%[^%\n]*ai[^%\n]*%%", re.IGNORECASE)


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
]
