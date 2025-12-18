from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.index.doctor import diagnose_index
from app.middleware.trace import TraceIdMiddleware
from app.observability import configure_metrics

try:
    from app.api.routes.ingest import router as ingest_router
except ImportError:
    ingest_router = None

try:
    from app.api.routes.search import router as search_router
except ImportError:
    search_router = None

try:
    from app.api.routes.status import router as status_router
except ImportError:
    status_router = None

try:
    from app.api.routes.ask import router as ask_router
except ImportError:
    ask_router = None

try:
    from app.api.routes.health import router as health_router
except ImportError:
    health_router = None

try:
    from app.api.routes.settings_validate import router as settings_validate_router
except ImportError:
    settings_validate_router = None

try:
    from app.api.routes.events_tail import router as events_tail_router
except ImportError:
    events_tail_router = None

try:
    from app.api.routes.health_contract import router as health_contract_router
except ImportError:
    health_contract_router = None

try:
    from app.api.routers.agent import router as agent_router
except ImportError:
    agent_router = None

static_dir = Path(__file__).resolve().parent.parent / "web" / "static"
logger = logging.getLogger(__name__)



def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@app.on_event("startup")
async def run_index_preflight() -> None:
    """Run the embeddings/index doctor in warn mode when enabled."""

    if not _truthy_env("EMBED_INDEX_PREFLIGHT", default=True):
        return
    try:
        result = diagnose_index()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Embedding index preflight failed: %s", exc)
        return

    issues = result.get("issues") or []
    warnings = result.get("warnings") or []
    if not issues and not warnings:
        return

    summary = "; ".join(issues or warnings)
    severity = "issues" if issues else "warnings"
    logger.warning(
        "Embedding index preflight detected %s: %s. Run `python -m app.cli index rebuild` to realign embeddings.",
        severity,
        summary,
    )


if ingest_router is not None:
    app.include_router(ingest_router)
if search_router is not None:
    app.include_router(search_router)
if status_router is not None:
    app.include_router(status_router, prefix="/api")
if ask_router is not None:
    app.include_router(ask_router, prefix="/api")
if agent_router is not None:
    app.include_router(agent_router)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Interim dashboard for status visibility and manual ASK checks."""
    index_path = static_dir / "index.html"
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


__all__ = ["app", "_create_app"]
