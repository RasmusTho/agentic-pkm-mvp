from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


DEFAULT_STANDARDS_PATH = Path("docs/settings/standards.yaml")


class StandardEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    scope: str = Field(..., min_length=1)
    canonical_refs: List[str] = Field(default_factory=list)


class StandardsRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    standards: List[StandardEntry] = Field(default_factory=list)


def load_standards_registry(path: Path | None = None) -> StandardsRegistry:
    p = path or DEFAULT_STANDARDS_PATH
    payload: Dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        return StandardsRegistry(**payload)
    except ValidationError as exc:
        raise ValueError(f"Invalid standards registry at {p}: {exc}") from exc
