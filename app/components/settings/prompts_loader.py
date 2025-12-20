from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.index.ingest_md import parse_markdown


DEFAULT_PROMPT_REGISTRY_PATH = Path("docs/settings/prompts/registry.yaml")


class PromptRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)
    status: str = Field("active")


class PromptRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    prompts: List[PromptRegistryEntry] = Field(default_factory=list)


@dataclass(frozen=True)
class PromptTemplate:
    prompt_id: str
    version: int
    status: str
    standards: List[str]
    inputs_schema: Optional[str]
    outputs_schema: Optional[str]
    allowed_models: List[str]
    body: str
    meta: Mapping[str, Any]
    path: Path


def _read_yaml(path: Path) -> Dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


def load_prompt_registry(path: Path | None = None) -> PromptRegistry:
    raw_path = os.getenv("PROMPT_REGISTRY_PATH")
    registry_path = Path(raw_path) if raw_path else (path or DEFAULT_PROMPT_REGISTRY_PATH)
    data = _read_yaml(registry_path)
    try:
        return PromptRegistry(**data)
    except ValidationError as exc:
        raise ValueError(f"Invalid prompt registry at {registry_path}: {exc}") from exc


def load_prompts(path: Path | None = None) -> Dict[str, PromptTemplate]:
    registry = load_prompt_registry(path=path)
    result: Dict[str, PromptTemplate] = {}

    for entry in registry.prompts:
        p = Path(entry.path)
        if not p.exists():
            raise FileNotFoundError(f"Prompt file not found for {entry.id}: {p}")

        meta, body = parse_markdown(p)
        prompt_id = str(meta.get("prompt_id") or "").strip()
        if prompt_id != entry.id:
            raise ValueError(f"Prompt id mismatch: registry={entry.id} frontmatter={prompt_id} path={p}")

        version = int(meta.get("version") or 1)
        status = str(meta.get("status") or entry.status)
        standards = meta.get("standards") or []
        if not isinstance(standards, list):
            standards = []
        standards = [str(x) for x in standards if str(x).strip()]

        allowed_models = meta.get("allowed_models") or []
        if not isinstance(allowed_models, list):
            allowed_models = []
        allowed_models = [str(x) for x in allowed_models if str(x).strip()]

        tpl = PromptTemplate(
            prompt_id=prompt_id,
            version=version,
            status=status,
            standards=standards,
            inputs_schema=str(meta.get("inputs_schema")) if meta.get("inputs_schema") else None,
            outputs_schema=str(meta.get("outputs_schema")) if meta.get("outputs_schema") else None,
            allowed_models=allowed_models,
            body=body,
            meta=meta,
            path=p,
        )
        result[entry.id] = tpl

    return result
