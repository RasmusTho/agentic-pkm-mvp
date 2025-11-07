from __future__ import annotations
from fastapi import APIRouter, Depends
from app.deps import get_agent_repository

router = APIRouter()

@router.get("/agent/health")
def agent_health(repo = Depends(get_agent_repository)) -> dict:
    hb = None
    if hasattr(repo, "get_last_heartbeat") and callable(getattr(repo, "get_last_heartbeat")):
        hb = repo.get_last_heartbeat()
    return {"heartbeat": hb or {"status": "unknown"}}
