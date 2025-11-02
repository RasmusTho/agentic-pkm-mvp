from __future__ import annotations
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from app.api._shim_helpers import interesting_items

router = APIRouter(tags=["dashboard"])

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    repo = getattr(request.app.state, "repo", None)
    items = interesting_items(repo) if repo is not None else []
    rows = []
    for item in items:
        payload = item.get("payload") or {}
        title = payload.get("title") or str(item.get("object_id", ""))
        score = item.get("score")
        rows.append(f"<li>{title} — score {score}</li>")
    body = f"<h1>Interesting Items</h1><ul>{''.join(rows) or '<li>None</li>'}</ul>"
    return HTMLResponse(f"<!doctype html><html><body>{body}</body></html>")
