from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


DEFAULT_MODEL_REGISTRY_PATH = Path("docs/settings/models/registry.yaml")


class ModelRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)
    status: str = Field("active")


class ModelRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    models: List[ModelRegistryEntry] = Field(default_factory=list)


class ModelPricing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    standard_input_usd_per_million_tokens: float = Field(..., gt=0)
    standard_output_usd_per_million_tokens: float = Field(..., gt=0)
    fast_mode_multiplier: float = Field(..., gt=0)
    source_urls: List[str] = Field(..., min_length=1)
    retrieved_on: date
    artificial_analysis_cost_per_intelligence_index_task_usd: Dict[str, float] = Field(
        default_factory=dict
    )


class ModelDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    status: str = Field("active")
    kind: str = Field(..., min_length=1)
    provider: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    dims: Optional[int] = None
    notes: Optional[str] = None
    pricing: Optional[ModelPricing] = None


def _read_yaml(path: Path) -> Dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


def load_model_registry(path: Path | None = None) -> ModelRegistry:
    raw_path = os.getenv("MODEL_REGISTRY_PATH")
    registry_path = Path(raw_path) if raw_path else (path or DEFAULT_MODEL_REGISTRY_PATH)
    data = _read_yaml(registry_path)
    try:
        return ModelRegistry(**data)
    except ValidationError as exc:
        raise ValueError(f"Invalid model registry at {registry_path}: {exc}") from exc


def load_models(path: Path | None = None) -> Dict[str, ModelDescriptor]:
    reg = load_model_registry(path=path)
    result: Dict[str, ModelDescriptor] = {}

    for entry in reg.models:
        p = Path(entry.path)
        if not p.exists():
            raise FileNotFoundError(f"Model file not found for {entry.id}: {p}")

        data = _read_yaml(p)
        try:
            md = ModelDescriptor(**data)
        except ValidationError as exc:
            raise ValueError(f"Invalid model descriptor {entry.id} at {p}: {exc}") from exc

        if md.id != entry.id:
            raise ValueError(f"Model id mismatch: registry={entry.id} file={md.id} path={p}")

        result[entry.id] = md

    return result
