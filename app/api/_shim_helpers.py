from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

# Enkel heartbeat-modell
@dataclass
class _Heartbeat:
    agent_id: str
    run_id: Optional[UUID]
    status: str
    created_at: datetime

class PostgresAgentRepository:
    """
    Minimal stub som uppfyller API:t som routrar och smoke-testen använder.
    Testerna monkeypatchar till sin egen repo – att denna klass finns räcker.
    """
    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn
        self._last_hb: Optional[_Heartbeat] = None
        # Används av smoke-testets StubService.start()
        self.interesting_items: dict[UUID, dict[str, Any]] = {}

    # Används av /agent/health
    def record_heartbeat(self, agent_id: str, run_id: Optional[UUID], status: str) -> None:
        self._last_hb = _Heartbeat(
            agent_id=agent_id,
            run_id=run_id,
            status=status,
            created_at=datetime.now(timezone.utc),
        )

    def get_last_heartbeat(self) -> Optional[dict[str, Any]]:
        if not self._last_hb:
            return None
        hb = self._last_hb
        return {
            "agent_id": hb.agent_id,
            "run_id": hb.run_id,
            "status": hb.status,
            "created_at": hb.created_at,
        }

    # Följande används av "interesting"-endpoints (om de anropas)
    def fetch_top_interesting(self, limit: int = 10) -> list[dict[str, Any]]:
        return list(self.interesting_items.values())[:limit]

    def interesting_summary(self) -> dict[str, Any]:
        items = self.fetch_top_interesting(10)
        return {"count": len(items)}

class AgentService:
    """
    Minimal stub som testet monkeypatchar över.
    """
    def __init__(self, repository: PostgresAgentRepository, config_manager: Any = None) -> None:
        self.repository = repository

    async def start(self) -> None:
        # No-op: i testen ersätts detta av en stub som skriver heartbeat + interesting.
        return None

    async def stop(self) -> None:
        return None
