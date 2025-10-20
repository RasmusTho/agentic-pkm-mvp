from __future__ import annotations

from fastapi import APIRouter, Depends

from app.agent.repository import AgentRepository
from app.deps import get_agent_repository

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/health")
def agent_health(repo: AgentRepository = Depends(get_agent_repository)) -> dict[str, object]:
    heartbeat = repo.get_last_heartbeat()
    if heartbeat and hasattr(heartbeat.get("last_seen"), "isoformat"):
        heartbeat["last_seen"] = heartbeat["last_seen"].isoformat()  # type: ignore[assignment]
    return {"heartbeat": heartbeat}
