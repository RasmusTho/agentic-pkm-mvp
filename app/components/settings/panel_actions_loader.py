from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from app.events.panel import PanelActionMapping
from app.index.ingest_md import parse_markdown

DEFAULT_PANEL_ACTIONS_PATH = Path("docs/settings/panel-actions.md")


def normalize_label(label: str) -> str:
    return " ".join(label.split()).strip().lower()


def _resolve_path(path: Path | None = None) -> Path | None:
    if path is not None:
        return Path(path)
    env_path = os.getenv("PANEL_ACTIONS_PATH") or os.getenv("PANEL_ACTIONS_FILE")
    if env_path:
        return Path(env_path)
    if DEFAULT_PANEL_ACTIONS_PATH.exists():
        return DEFAULT_PANEL_ACTIONS_PATH
    return None


def _coerce_mapping(entry: Any) -> dict[str, Any]:
    if isinstance(entry, dict):
        return dict(entry)
    try:
        # Pydantic models or other objects with dict()
        if hasattr(entry, "dict"):
            return dict(entry.dict())  # type: ignore[call-arg]
        if hasattr(entry, "model_dump"):
            return dict(entry.model_dump())  # type: ignore[attr-defined]
    except Exception:
        pass
    return {}


def _load_from_frontmatter(path: Path) -> list[dict[str, Any]]:
    frontmatter, _ = parse_markdown(path)
    mappings = frontmatter.get("mappings")
    if not isinstance(mappings, list):
        return []
    return [_coerce_mapping(entry) for entry in mappings]


def _entry_to_mapping(entry: dict[str, Any]) -> tuple[str, PanelActionMapping] | None:
    label = str(entry.get("label") or entry.get("text") or "").strip()
    downstream_event = str(entry.get("downstream_event") or entry.get("event_type") or "").strip()
    intent_type = str(entry.get("intent_type") or entry.get("intent") or "").strip()
    params = entry.get("params") or entry.get("payload_template") or {}
    action_id = str(entry.get("id") or "").strip() or normalize_label(label)
    if not label or not downstream_event or not intent_type:
        return None
    mapping = PanelActionMapping(
        id=action_id,
        intent_type=intent_type,
        downstream_event=downstream_event,
        params=dict(params) if isinstance(params, dict) else {},
    )
    return normalize_label(label), mapping


def load_panel_action_mapping(path: Path | None = None) -> dict[str, PanelActionMapping]:
    """
    Load panel action mappings from a markdown settings file (frontmatter 'mappings' list).
    Returns a dict keyed by normalized label for deterministic lookup.
    """
    resolved = _resolve_path(path)
    if resolved is None or not resolved.exists():
        return {}

    entries = _load_from_frontmatter(resolved)
    mappings: Dict[str, PanelActionMapping] = {}
    for entry in entries:
        parsed = _entry_to_mapping(entry)
        if not parsed:
            continue
        key, mapping = parsed
        mappings[key] = mapping
    return mappings


__all__ = ["load_panel_action_mapping", "normalize_label", "DEFAULT_PANEL_ACTIONS_PATH"]
