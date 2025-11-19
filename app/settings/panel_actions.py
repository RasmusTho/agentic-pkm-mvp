from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.index.ingest_md import parse_markdown

DEFAULT_PANEL_ACTIONS_ROOT = Path("vault/_system/panel-actions")
FALLBACK_PANEL_ACTIONS_ROOT = Path("docs/settings/panel-actions")
FALLBACK_PANEL_ACTIONS_FILE = Path("docs/settings/panel-actions.md")


class PanelActionMapping(BaseModel):
    text: str
    event_type: str
    payload_template: Dict[str, Any] = Field(default_factory=dict)


def _resolve_root(root: Optional[Path] = None) -> Optional[Path]:
    if root is not None:
        return Path(root)
    env = os.getenv("PANEL_ACTIONS_ROOT", "").strip()
    if env:
        return Path(env)
    if DEFAULT_PANEL_ACTIONS_ROOT.exists():
        return DEFAULT_PANEL_ACTIONS_ROOT
    if FALLBACK_PANEL_ACTIONS_ROOT.exists():
        return FALLBACK_PANEL_ACTIONS_ROOT
    if FALLBACK_PANEL_ACTIONS_FILE.exists():
        return FALLBACK_PANEL_ACTIONS_FILE
    return None


def _normalize_entry(entry: Any) -> Dict[str, Any]:
    if isinstance(entry, PanelActionMapping):
        return entry.model_dump()
    if isinstance(entry, dict):
        return dict(entry)
    return {"text": str(entry)}


def _load_mappings_from_file(path: Path) -> List[PanelActionMapping]:
    frontmatter, _ = parse_markdown(path)
    mappings_data = (frontmatter or {}).get("mappings")
    mappings: List[PanelActionMapping] = []
    if not isinstance(mappings_data, list):
        return mappings
    for entry in mappings_data:
        normalized = _normalize_entry(entry)
        text = str(normalized.get("text", "")).strip()
        event_type = str(normalized.get("event_type", "")).strip()
        payload_template = normalized.get("payload_template") or {}
        if not text or not event_type:
            continue
        mappings.append(
            PanelActionMapping(
                text=text,
                event_type=event_type,
                payload_template=dict(payload_template) if isinstance(payload_template, dict) else {},
            )
        )
    return mappings


def load_panel_action_mappings(root: Optional[Path] = None) -> Dict[str, PanelActionMapping]:
    resolved = _resolve_root(root)
    if resolved is None or not resolved.exists():
        return {}
    paths: List[Path]
    if resolved.is_file():
        paths = [resolved]
    else:
        paths = sorted(resolved.glob("*.md"))
    mappings: Dict[str, PanelActionMapping] = {}
    for path in paths:
        for mapping in _load_mappings_from_file(path):
            mappings[mapping.text] = mapping
    return mappings


__all__ = ["PanelActionMapping", "load_panel_action_mappings"]
