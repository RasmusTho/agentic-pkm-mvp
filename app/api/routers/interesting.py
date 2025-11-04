from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Request
from app.api._shim_helpers import interesting_items

router = APIRouter(tags=["interesting"])

@router.get("/interesting")
def list_interesting(request: Request) -> dict[str, Any]:
    repo = getattr(request.app.state, "repo", None)
    items = interesting_items(repo) if repo is not None else []
    return {"items": items, "ok": True}
