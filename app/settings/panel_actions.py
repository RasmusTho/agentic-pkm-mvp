from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.index.ingest_md import parse_markdown

_BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PANEL_ACTIONS_ROOT = _BASE_DIR / "vault" / "_system" / "panel-actions"
FALLBACK_PANEL_ACTIONS_ROOT = _BASE_DIR / "docs" / "settings" / "panel-actions"
FALLBACK_PANEL_ACTIONS_FILE = _BASE_DIR / "docs" / "settings" / "panel-actions.md"


class PanelActionMapping(BaseModel):
    text: str
    event_type: str
    payload_template: Dict[str, Any] = Field(default_factory=dict)
    action_id: str | None = None


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


def _entries_to_mappings(entry: Any) -> list[PanelActionMapping]:
    normalized = _normalize_entry(entry)
    labels = normalized.get("labels") or []
    label = normalized.get("label") or normalized.get("text") or normalized.get("name") or ""
    if label:
        labels = [label, *labels]
    labels = [str(l).strip() for l in labels if str(l).strip()]
    action_id = str(normalized.get("id") or "").strip() or None
    intent_type = str(normalized.get("intent_type") or normalized.get("intent") or "").strip().lower()
    raw_event_type = str(normalized.get("event_type") or normalized.get("downstream_event") or "").strip()
    payload_template = normalized.get("payload_template") or normalized.get("params") or {}
    if not isinstance(payload_template, dict):
        payload_template = {}

    if intent_type == "promotion":
        if raw_event_type and raw_event_type != "promote.intent.created":
            payload_template.setdefault("downstream_event", raw_event_type)
        event_type = "promote.intent.created"
    else:
        event_type = raw_event_type

    if not labels and action_id:
        labels = [action_id]
    if not labels and normalized.get("text"):
        labels = [str(normalized["text"]).strip()]

    mappings: list[PanelActionMapping] = []
    for lbl in labels:
        if not event_type:
            continue
        mappings.append(
            PanelActionMapping(
                text=lbl,
                event_type=event_type,
                payload_template=dict(payload_template),
                action_id=action_id,
            )
        )
    return mappings


def _load_mappings_from_file(path: Path) -> List[PanelActionMapping]:
    frontmatter, _ = parse_markdown(path)
    mappings_data = (frontmatter or {}).get("mappings")
    mappings: List[PanelActionMapping] = []
    if not isinstance(mappings_data, list):
        return mappings
    for entry in mappings_data:
        mappings.extend(_entries_to_mappings(entry))
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
