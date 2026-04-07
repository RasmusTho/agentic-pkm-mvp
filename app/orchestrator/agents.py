from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.settings.agents import AgentConfig, load_agent_configs


@dataclass
class AgentPermissionError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def _normalize_agent_target(agent_target: str) -> str:
    if not agent_target:
        return ""
    if ":" in agent_target:
        _, _, remainder = agent_target.partition(":")
        return remainder.strip()
    return agent_target.strip()


def resolve_agent_config(
    agent_target: str,
    flow_id: Optional[str] = None,
    event_type: Optional[str] = None,
) -> Optional[AgentConfig]:
    configs = load_agent_configs()
    normalized = _normalize_agent_target(agent_target)
    return configs.get(normalized)


def validate_agent_permissions(
    config: AgentConfig,
    flow_id: Optional[str],
    event_type: Optional[str],
) -> None:
    if not config.enabled:
        raise AgentPermissionError(f"agent '{config.agent_id}' is disabled")
    if config.flows and flow_id not in config.flows:
        raise AgentPermissionError(f"agent '{config.agent_id}' not allowed for flow '{flow_id}'")
    if config.allowed_events and event_type not in config.allowed_events:
        raise AgentPermissionError(f"agent '{config.agent_id}' not allowed for event '{event_type}'")


__all__ = ["AgentPermissionError", "_normalize_agent_target", "resolve_agent_config", "validate_agent_permissions"]
