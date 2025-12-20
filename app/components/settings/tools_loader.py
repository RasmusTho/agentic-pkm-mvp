from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


DEFAULT_TOOL_REGISTRY_PATH = Path("docs/settings/tools/registry.yaml")


class ToolRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)
    status: str = Field("active")


class ToolRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    tools: List[ToolRegistryEntry] = Field(default_factory=list)


class ToolDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    status: str = Field("active")
    protocol: str = Field(..., min_length=1)
    server: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    allowed_args: Mapping[str, Any] = Field(default_factory=dict)
    mock_result: Optional[Mapping[str, Any]] = None


def _read_yaml(path: Path) -> Dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


def load_tool_registry(path: Path | None = None) -> ToolRegistry:
    raw_path = os.getenv("TOOL_REGISTRY_PATH")
    registry_path = Path(raw_path) if raw_path else (path or DEFAULT_TOOL_REGISTRY_PATH)
    data = _read_yaml(registry_path)
    try:
        return ToolRegistry(**data)
    except ValidationError as exc:
        raise ValueError(f"Invalid tool registry at {registry_path}: {exc}") from exc


def load_tools(path: Path | None = None) -> Dict[str, ToolDescriptor]:
    reg = load_tool_registry(path=path)
    result: Dict[str, ToolDescriptor] = {}

    for entry in reg.tools:
        p = Path(entry.path)
        if not p.exists():
            raise FileNotFoundError(f"Tool file not found for {entry.id}: {p}")

        data = _read_yaml(p)
        try:
            td = ToolDescriptor(**data)
        except ValidationError as exc:
            raise ValueError(f"Invalid tool descriptor {entry.id} at {p}: {exc}") from exc

        if td.id != entry.id:
            raise ValueError(f"Tool id mismatch: registry={entry.id} file={td.id} path={p}")

        result[entry.id] = td

    return result
