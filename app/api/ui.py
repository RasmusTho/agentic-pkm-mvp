from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.agent.repository import AgentRepository
from app.deps import get_agent_repository

router = APIRouter(tags=["ui"])


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    system_intent: str | None = None,
    tag: str | None = None,
    repo: AgentRepository = Depends(get_agent_repository),
) -> str:
    items = repo.fetch_top_interesting(limit=10, system_intent=system_intent, tag=tag)
    rows = "".join(
        f"<tr><td>{idx + 1}</td><td>{item['reason']}</td><td>{item['score']:.3f}</td>"
        f"<td>{item['novelty']:.2f}/{item['anomaly']:.2f}/{item['uncertainty']:.2f}/{item['value']:.2f}</td></tr>"
        for idx, item in enumerate(items)
    )
    filters = []
    if system_intent:
        filters.append(f"Intent: {system_intent}")
    if tag:
        filters.append(f"Tag: {tag}")
    subtitle = " | ".join(filters)
    subtitle_html = f"<p>{subtitle}</p>" if subtitle else ""
    empty_row = "<tr><td colspan='4'>No interesting items yet</td></tr>"
    tbody = f"<tbody>{rows or empty_row}</tbody>"
    return (
        "<html><head><title>Agent Dashboard</title></head>"
        "<body><h1>Interesting Items</h1>"
        f"{subtitle_html}"
        "<table border='1' cellpadding='6'>"
        "<thead><tr><th>#</th><th>Reason</th><th>Score</th><th>Metrics (N/A/U/V)</th></tr></thead>"
        f"{tbody}</table></body></html>"
    )
