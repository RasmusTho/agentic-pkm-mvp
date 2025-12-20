from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


DEFAULT_AGENT_REGISTRY_PATH = Path("docs/settings/agents/registry.yaml")


class AgentRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)
    status: str = Field("active")


class AgentRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    agents: List[AgentRegistryEntry] = Field(default_factory=list)


class AgentDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    status: str = Field("active")
    kind: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)

    entrypoint: str = Field(..., min_length=1)
    state_schema: Optional[str] = None

    input_events: List[str] = Field(default_factory=list)
    output_events: List[str] = Field(default_factory=list)

    allowed_tools: List[str] = Field(default_factory=list)
    allowed_stores: List[str] = Field(default_factory=list)

    settings_refs: List[str] = Field(default_factory=list)


def _read_yaml(path: Path) -> Dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


def load_agent_registry(path: Path | None = None) -> AgentRegistry:
    raw_path = os.getenv("AGENT_REGISTRY_PATH")
    registry_path = Path(raw_path) if raw_path else (path or DEFAULT_AGENT_REGISTRY_PATH)
    data = _read_yaml(registry_path)
    try:
        return AgentRegistry(**data)
    except ValidationError as exc:
        raise ValueError(f"Invalid agent registry at {registry_path}: {exc}") from exc


def load_agents(path: Path | None = None) -> Dict[str, AgentDescriptor]:
    reg = load_agent_registry(path=path)
    result: Dict[str, AgentDescriptor] = {}

    for entry in reg.agents:
        p = Path(entry.path)
        if not p.exists():
            raise FileNotFoundError(f"Agent file not found for {entry.id}: {p}")

        data = _read_yaml(p)
        try:
            ad = AgentDescriptor(**data)
        except ValidationError as exc:
            raise ValueError(f"Invalid agent descriptor {entry.id} at {p}: {exc}") from exc

        if ad.id != entry.id:
            raise ValueError(f"Agent id mismatch: registry={entry.id} file={ad.id} path={p}")

        result[entry.id] = ad

    return result
