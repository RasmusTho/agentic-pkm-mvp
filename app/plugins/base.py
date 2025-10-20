from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

if False:  # pragma: no cover - type checking only
    from app.agent.repository import AgentRepository
    from app.config.agent import AgentConfig


@dataclass(slots=True)
class ToolContext:
    run_id: UUID
    config: "AgentConfig"
    repository: "AgentRepository"


@dataclass(slots=True)
class ToolResult:
    name: str
    output: Any
    metadata: dict[str, Any] | None = None


class Tool(Protocol):
    name: str

    async def arun(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        ...
