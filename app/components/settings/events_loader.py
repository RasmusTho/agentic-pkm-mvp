from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


DEFAULT_EVENT_REGISTRY_PATH = Path("docs/settings/events/registry.yaml")


class EventRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)
    status: str = Field("active")


class EventRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    events: List[EventRegistryEntry] = Field(default_factory=list)


class EventDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    status: str = Field("active")
    version: int = Field(1, ge=1)
    description: str = Field(..., min_length=1)
    schema_ref: Optional[str] = None
    producers: List[str] = Field(default_factory=list)
    consumers: List[str] = Field(default_factory=list)


def _read_yaml(path: Path) -> Dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


def load_event_registry(path: Path | None = None) -> EventRegistry:
    raw_path = os.getenv("EVENT_REGISTRY_PATH")
    registry_path = Path(raw_path) if raw_path else (path or DEFAULT_EVENT_REGISTRY_PATH)
    data = _read_yaml(registry_path)
    try:
        return EventRegistry(**data)
    except ValidationError as exc:
        raise ValueError(f"Invalid event registry at {registry_path}: {exc}") from exc


def load_events(path: Path | None = None) -> Dict[str, EventDescriptor]:
    reg = load_event_registry(path=path)
    result: Dict[str, EventDescriptor] = {}

    for entry in reg.events:
        p = Path(entry.path)
        if not p.exists():
            raise FileNotFoundError(f"Event file not found for {entry.id}: {p}")

        data = _read_yaml(p)
        try:
            ed = EventDescriptor(**data)
        except ValidationError as exc:
            raise ValueError(f"Invalid event descriptor {entry.id} at {p}: {exc}") from exc

        if ed.id != entry.id:
            raise ValueError(f"Event id mismatch: registry={entry.id} file={ed.id} path={p}")

        if ed.schema_ref and not Path(ed.schema_ref).exists():
            raise FileNotFoundError(f"{ed.id} schema_ref not found: {ed.schema_ref}")

        result[entry.id] = ed

    return result
