from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.index.ingest_md import parse_markdown

DEFAULT_FLOWS_ROOT = Path("vault/_system/flows")
FALLBACK_FLOWS_ROOT = Path("docs/settings/sample-flows")


class PatternStep(BaseModel):
    target: str
    description: Optional[str] = None
    intent: Optional[str] = None
    args: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SuggestedPattern(BaseModel):
    name: str
    description: Optional[str] = None
    steps: List[PatternStep] = Field(default_factory=list)


class PromptProfile(BaseModel):
    id: str
    description: Optional[str] = None
    prompt_template_ref: str


class PlannerMode(BaseModel):
    strictness: Literal["advisory", "balanced", "strict"] = "balanced"
    max_steps: int = 8


class FlowProfile(BaseModel):
    flow_id: str
    name: Optional[str] = None
    enabled: bool = True
    event_triggers: List[str] = Field(default_factory=list)
    intent: Optional[str] = None
    suggested_patterns: List[SuggestedPattern] = Field(default_factory=list)
    planner_mode: PlannerMode = Field(default_factory=PlannerMode)
    prompt_profiles: List[PromptProfile] = Field(default_factory=list)


def _resolve_root(root: Optional[Path] = None) -> Optional[Path]:
    if root is not None:
        return Path(root)
    env = os.getenv("FLOW_PROFILES_ROOT", "").strip()
    if env:
        return Path(env)
    if DEFAULT_FLOWS_ROOT.exists():
        return DEFAULT_FLOWS_ROOT
    if FALLBACK_FLOWS_ROOT.exists():
        return FALLBACK_FLOWS_ROOT
    return None


def _normalize_step_entry(step: Any) -> Dict[str, Any]:
    if isinstance(step, PatternStep):
        return step.model_dump()
    if isinstance(step, dict):
        normalized = dict(step)
        normalized["target"] = str(normalized.get("target", "")).strip()
        return normalized
    return {"target": str(step).strip()}


def _normalize_patterns(data: Dict[str, Any]) -> None:
    patterns = data.get("suggested_patterns")
    if not isinstance(patterns, list):
        return
    normalized_patterns: List[Dict[str, Any]] = []
    for pattern in patterns:
        if not isinstance(pattern, dict):
            continue
        pattern_copy = dict(pattern)
        steps = pattern_copy.get("steps")
        if isinstance(steps, list):
            pattern_copy["steps"] = [_normalize_step_entry(step) for step in steps]
        normalized_patterns.append(pattern_copy)
    data["suggested_patterns"] = normalized_patterns


def _load_profile(path: Path) -> FlowProfile:
    frontmatter, _ = parse_markdown(path)
    data = dict(frontmatter or {})
    data.setdefault("flow_id", path.stem)
    _normalize_patterns(data)
    return FlowProfile(**data)


def load_flow_profiles(root: Optional[Path] = None) -> Dict[str, FlowProfile]:
    resolved = _resolve_root(root)
    if resolved is None or not resolved.exists():
        return {}
    profiles: Dict[str, FlowProfile] = {}
    for md_file in sorted(resolved.glob("*.md")):
        profile = _load_profile(md_file)
        profiles[profile.flow_id] = profile
    return profiles


def get_flows_for_event(
    event_type: str, profiles: Optional[Dict[str, FlowProfile]] = None
) -> List[FlowProfile]:
    active = profiles or load_flow_profiles()
    matches: List[FlowProfile] = []
    for profile in active.values():
        if not profile.enabled:
            continue
        if event_type in profile.event_triggers:
            matches.append(profile)
    return matches


def get_flow(flow_id: str, profiles: Optional[Dict[str, FlowProfile]] = None) -> Optional[FlowProfile]:
    active = profiles or load_flow_profiles()
    return active.get(flow_id)


__all__ = [
    "PatternStep",
    "SuggestedPattern",
    "PromptProfile",
    "PlannerMode",
    "FlowProfile",
    "load_flow_profiles",
    "get_flows_for_event",
    "get_flow",
]
