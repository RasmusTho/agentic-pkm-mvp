from __future__ import annotations

import os
from typing import Dict

from app.components.settings.agents_loader import load_agents


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def is_policy_enforced() -> bool:
    return _truthy(os.getenv("POLICY_ENFORCE"))


def assert_tool_allowed(agent_id: str | None, tool_id: str) -> None:
    if not is_policy_enforced():
        return
    if not agent_id:
        raise PermissionError("Policy enforcement enabled but agent_id missing")

    agents: Dict[str, object] = load_agents()
    agent = agents.get(agent_id)
    if agent is None:
        raise PermissionError(f"Agent {agent_id} not found in registry")

    allowed = set(getattr(agent, "allowed_tools", []) or [])
    if tool_id not in allowed:
        raise PermissionError(f"Tool {tool_id} not allowed for agent {agent_id} (POLICY_ENFORCE=1)")
