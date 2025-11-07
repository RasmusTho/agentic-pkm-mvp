from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from app.deps import get_agent_repository

if TYPE_CHECKING:  # pragma: no cover - type-checking helper
    from app.agent.repository import AgentRepository

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/health")
def agent_health(repo: "AgentRepository" = Depends(get_agent_repository)) -> dict[str, object]:
    heartbeat = repo.get_last_heartbeat()
    if heartbeat and hasattr(heartbeat.get("last_seen"), "isoformat"):
        heartbeat["last_seen"] = heartbeat["last_seen"].isoformat()  # type: ignore[assignment]
    return {"heartbeat": heartbeat}
