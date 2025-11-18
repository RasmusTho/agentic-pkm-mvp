from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.index.ingest_md import parse_markdown

DEFAULT_AGENTS_ROOT = Path("vault/_system/agents")
FALLBACK_AGENTS_ROOT = Path("docs/settings/sample-agents")


class ModelConfig(BaseModel):
    provider: str
    name: str
    temperature: float = 0.0
    max_tokens: int = 1024


class AgentConfig(BaseModel):
    agent_id: str
    agent_type: str
    enabled: bool = True
    flows: List[str] = Field(default_factory=list)
    allowed_targets: List[str] = Field(default_factory=list)
    allowed_events: List[str] = Field(default_factory=list)
    model: Optional[ModelConfig] = None
    tools: List[str] = Field(default_factory=list)
    prompt_template_ref: Optional[str] = None


def _resolve_root(root: Optional[Path] = None) -> Optional[Path]:
    if root is not None:
        return Path(root)
    env = os.getenv("AGENT_CONFIGS_ROOT", "").strip()
    if env:
        return Path(env)
    if DEFAULT_AGENTS_ROOT.exists():
        return DEFAULT_AGENTS_ROOT
    if FALLBACK_AGENTS_ROOT.exists():
        return FALLBACK_AGENTS_ROOT
    return None


def _load_agent(path: Path) -> AgentConfig:
    frontmatter, _ = parse_markdown(path)
    data = dict(frontmatter or {})
    data.setdefault("agent_id", path.stem)
    return AgentConfig(**data)


def load_agent_configs(root: Optional[Path] = None) -> Dict[str, AgentConfig]:
    resolved = _resolve_root(root)
    if resolved is None or not resolved.exists():
        return {}
    configs: Dict[str, AgentConfig] = {}
    for md_file in sorted(resolved.glob("*.md")):
        agent = _load_agent(md_file)
        configs[agent.agent_id] = agent
    return configs


def get_agent_config(agent_id: str, configs: Optional[Dict[str, AgentConfig]] = None) -> Optional[AgentConfig]:
    active = configs or load_agent_configs()
    return active.get(agent_id)


def get_agents_for_flow(flow_id: str, configs: Optional[Dict[str, AgentConfig]] = None) -> List[AgentConfig]:
    active = configs or load_agent_configs()
    matches: List[AgentConfig] = []
    for agent in active.values():
        if not agent.enabled:
            continue
        if flow_id in agent.flows:
            matches.append(agent)
    return matches


__all__ = [
    "ModelConfig",
    "AgentConfig",
    "load_agent_configs",
    "get_agent_config",
    "get_agents_for_flow",
]
