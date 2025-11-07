from __future__ import annotations
from fastapi import APIRouter, Depends
from app.deps import get_agent_repository

router = APIRouter()

@router.get("/interesting")
def interesting(repo = Depends(get_agent_repository)) -> dict:
    items = []
    if hasattr(repo, "interesting_items"):
        raw = getattr(repo, "interesting_items") or {}
        if isinstance(raw, dict):
            items = list(raw.values())
    elif hasattr(repo, "fetch_top_interesting") and callable(repo.fetch_top_interesting):  # type: ignore[attr-defined]
        items = repo.fetch_top_interesting()  # type: ignore
    return {"items": items}

@router.get("/interesting/summary")
def interesting_summary(repo = Depends(get_agent_repository)) -> dict:
    if hasattr(repo, "interesting_summary"):
        val = getattr(repo, "interesting_summary")
        return val() if callable(val) else (val or {})
    return {}
