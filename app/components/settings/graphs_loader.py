from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


DEFAULT_GRAPH_REGISTRY_PATH = Path("docs/settings/graphs/registry.yaml")


class GraphRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)
    status: str = Field("active")


class GraphRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    graphs: List[GraphRegistryEntry] = Field(default_factory=list)


class GraphDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    status: str = Field("active")
    agent_id: str = Field(..., min_length=1)
    kind: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)

    entrypoint: str = Field(..., min_length=1)
    state_schema: Optional[str] = None

    input_events: List[str] = Field(default_factory=list)
    output_events: List[str] = Field(default_factory=list)


def _read_yaml(path: Path) -> Dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


def load_graph_registry(path: Path | None = None) -> GraphRegistry:
    raw_path = os.getenv("GRAPH_REGISTRY_PATH")
    registry_path = Path(raw_path) if raw_path else (path or DEFAULT_GRAPH_REGISTRY_PATH)
    data = _read_yaml(registry_path)
    try:
        return GraphRegistry(**data)
    except ValidationError as exc:
        raise ValueError(f"Invalid graph registry at {registry_path}: {exc}") from exc


def load_graphs(path: Path | None = None) -> Dict[str, GraphDescriptor]:
    reg = load_graph_registry(path=path)
    result: Dict[str, GraphDescriptor] = {}

    for entry in reg.graphs:
        p = Path(entry.path)
        if not p.exists():
            raise FileNotFoundError(f"Graph file not found for {entry.id}: {p}")

        data = _read_yaml(p)
        try:
            gd = GraphDescriptor(**data)
        except ValidationError as exc:
            raise ValueError(f"Invalid graph descriptor {entry.id} at {p}: {exc}") from exc

        if gd.id != entry.id:
            raise ValueError(f"Graph id mismatch: registry={entry.id} file={gd.id} path={p}")

        result[entry.id] = gd

    return result
