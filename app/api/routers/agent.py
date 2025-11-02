from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Request
from app.api._shim_helpers import latest_heartbeat

router = APIRouter(prefix="/agent", tags=["agent"])

@router.get("/health")
def agent_health(request: Request) -> dict[str, Any]:
    repo = getattr(request.app.state, "repo", None)
    hb = latest_heartbeat(repo) if repo is not None else None
    return {"ok": True, "heartbeat": hb or {"status": "unknown"}}
