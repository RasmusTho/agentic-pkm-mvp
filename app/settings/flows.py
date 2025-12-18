from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

import yaml
from pydantic import BaseModel, Field

from app.config.paths import resolve_flow_settings_path

DEFAULT_FLOW_PATH = Path("vault/_system/settings/flows.settings.yaml")
FALLBACK_FLOW_PATH = Path("docs/settings/flows.settings.yaml")

_cached_path: Path | None = None
_cached_mtime: float | None = None
_cached: "FlowsSettings" | None = None


class FlowConfig(BaseModel):
    enabled: bool = True
    triggers: List[str] = Field(default_factory=list)


class FlowsSettings(BaseModel):
    flows: Dict[str, FlowConfig] = Field(default_factory=dict)


def _resolve_path(path: Path | None = None) -> Path | None:
    resolved = resolve_flow_settings_path(path)
    if resolved is None:
        return None
    if resolved.exists():
        return resolved
    if DEFAULT_FLOW_PATH.exists():
        return DEFAULT_FLOW_PATH
    if FALLBACK_FLOW_PATH.exists():
        return FALLBACK_FLOW_PATH
    return resolved


def load_flow_settings(force: bool = False, path: Path | None = None) -> FlowsSettings:
    global _cached, _cached_mtime, _cached_path
    resolved = _resolve_path(path)
    if resolved is None:
        return _cached or FlowsSettings()
    mtime = resolved.stat().st_mtime if resolved.exists() else None
    if not force and _cached and _cached_path == resolved and _cached_mtime == mtime:
        return _cached
    if not resolved.exists():
        settings = FlowsSettings()
        _cached = settings
        _cached_path = resolved
        _cached_mtime = mtime
        return settings
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("flow settings must be a mapping with 'flows' key")
    flows_section = raw.get("flows") or {}
    flows: Dict[str, FlowConfig] = {}
    for name, cfg in flows_section.items():
        if isinstance(cfg, dict):
            flows[name] = FlowConfig(**cfg)
    settings = FlowsSettings(flows=flows)
    _cached = settings
    _cached_mtime = mtime
    _cached_path = resolved
    return settings


def get_active_flows(force: bool = False) -> FlowsSettings:
    return load_flow_settings(force=force)


def get_flows_for_event(event_type: str, settings: FlowsSettings | None = None) -> List[str]:
    flows = settings or load_flow_settings()
    matches: List[str] = []
    for name, cfg in flows.flows.items():
        if not cfg.enabled:
            continue
        if event_type in cfg.triggers:
            matches.append(name)
    return matches


__all__ = ["FlowConfig", "FlowsSettings", "load_flow_settings", "get_active_flows", "get_flows_for_event"]
