from __future__ import annotations
from typing import Any

class PostgresAgentRepository:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

class AgentService:
    def __init__(self, repository: PostgresAgentRepository, config_manager: Any = None) -> None:
        self.repository = repository
    async def start(self) -> None:
        return None
    async def stop(self) -> None:
        return None
