from __future__ import annotations

from typing import Any, Mapping

AutoRunMode = str  # "manual" | "watcher" | "never"


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


def watcher_may_run_panel(frontmatter: Mapping[str, Any]) -> bool:
    """
    True when watcher-driven panel runtime is allowed for this note.
    Manual CLI runs are always allowed.
    """
    return get_auto_run_mode(frontmatter) == "watcher"


__all__ = ["get_auto_run_mode", "watcher_may_run_panel"]
