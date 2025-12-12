from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.events.panel import PanelActionMapping
from app.index.ingest_md import parse_markdown

DEFAULT_PANEL_ACTIONS_PATH = Path("docs/settings/panel-actions.md")


def normalize_label(label: str) -> str:
    return " ".join(label.split()).strip().lower()


class PanelActionDescriptor(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    intent_type: str
    downstream_event: str
    kind: str | None = None
    description: str | None = None
    llm_hint: str | None = None
    labels: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)
    watcher_allowed: bool = True
    manual_only: bool = False

    def to_mapping(self) -> PanelActionMapping:
        return PanelActionMapping(
            id=self.id,
            intent_type=self.intent_type,
            downstream_event=self.downstream_event,
            params=self.params,
        )

    def all_labels(self) -> list[str]:
        return [lbl for lbl in (self.labels or []) if lbl] + [alias for alias in (self.aliases or []) if alias]


class PanelActionCatalog(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    actions: List[PanelActionDescriptor] = Field(default_factory=list)
    label_index: Dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_descriptors(cls, descriptors: Iterable[PanelActionDescriptor]) -> "PanelActionCatalog":
        label_index: Dict[str, str] = {}
        for descriptor in descriptors:
            labels = descriptor.all_labels() or [descriptor.id]
            for label in labels:
                key = normalize_label(label)
                if key and key not in label_index:
                    label_index[key] = descriptor.id
        return cls(actions=list(descriptors), label_index=label_index)

    def find_by_label(self, label: str) -> Optional[PanelActionDescriptor]:
        key = normalize_label(label)
        action_id = self.label_index.get(key)
        if not action_id:
            return None
        return self.get(action_id)

    def get(self, action_id: str) -> Optional[PanelActionDescriptor]:
        for action in self.actions:
            if action.id == action_id:
                return action
        return None

    def ids(self) -> set[str]:
        return {a.id for a in self.actions}


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


def _entry_to_descriptor(entry: dict[str, Any]) -> PanelActionDescriptor | None:
    label = str(entry.get("label") or entry.get("text") or "").strip()
    labels: list[str] = []
    if label:
        labels.append(label)
    labels.extend(entry.get("labels") or [])
    aliases = entry.get("aliases") or entry.get("synonyms") or []
    downstream_event = str(entry.get("downstream_event") or entry.get("event_type") or "").strip()
    intent_type = str(entry.get("intent_type") or entry.get("intent") or "").strip()
    params = entry.get("params") or entry.get("payload_template") or {}
    action_id = str(entry.get("id") or "").strip() or (normalize_label(label) if label else "")
    if not action_id or not downstream_event or not intent_type:
        return None

    return PanelActionDescriptor(
        id=action_id,
        intent_type=intent_type,
        downstream_event=downstream_event,
        kind=str(entry.get("kind") or entry.get("category") or "") or None,
        description=str(entry.get("description") or "") or None,
        llm_hint=str(entry.get("llm_hint") or entry.get("hint") or "") or None,
        labels=labels,
        aliases=[str(a) for a in aliases if a],
        params=dict(params) if isinstance(params, dict) else {},
        watcher_allowed=bool(entry.get("watcher_allowed", True)),
        manual_only=bool(entry.get("manual_only", False)),
    )


def load_panel_action_catalog(path: Path | None = None) -> PanelActionCatalog:
    resolved = _resolve_path(path)
    if resolved is None or not resolved.exists():
        return PanelActionCatalog(actions=[], label_index={})

    entries = _load_from_frontmatter(resolved)
    descriptors: list[PanelActionDescriptor] = []
    for entry in entries:
        descriptor = _entry_to_descriptor(entry)
        if descriptor:
            descriptors.append(descriptor)
    return PanelActionCatalog.from_descriptors(descriptors)


def load_panel_action_mapping(path: Path | None = None) -> dict[str, PanelActionMapping]:
    """
    Backward-compatible mapping keyed by normalized label for deterministic lookup.
    """
    catalog = load_panel_action_catalog(path)
    mappings: Dict[str, PanelActionMapping] = {}
    for label, action_id in catalog.label_index.items():
        descriptor = catalog.get(action_id)
        if not descriptor:
            continue
        mappings[label] = descriptor.to_mapping()
    return mappings


__all__ = [
    "load_panel_action_mapping",
    "load_panel_action_catalog",
    "normalize_label",
    "DEFAULT_PANEL_ACTIONS_PATH",
    "PanelActionCatalog",
    "PanelActionDescriptor",
]
