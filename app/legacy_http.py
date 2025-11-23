"""Legacy FastAPI app exposing agent + dashboard demo endpoints.

Kept for smoke/manual checks; not the canonical Reality-MVP HTTP API."""

from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI

engine = None
SessionLocal = None

# Stubs (inga psycopg-importer här)
from app.api._shim_helpers import PostgresAgentRepository, AgentService

# Routers (enda källan till endpoints)
from app.api.routers.agent import router as agent_router
from app.api.routers.interesting import router as interesting_router
from app.api.routers.dashboard import router as dashboard_router

_repo = None
_service_instance = None


async def _start(app: FastAPI) -> None:
    global _repo, _service_instance
    try:
        _repo = PostgresAgentRepository("dsn://stub")
        app.state.agent_repository = _repo  # type: ignore[attr-defined]
        _service_instance = AgentService(_repo, None)
        start = getattr(_service_instance, "start", None)
        if callable(start):
            await start()
    except Exception:
        _service_instance = None


async def _stop(app: FastAPI) -> None:
    global _service_instance
    try:
        if _service_instance is not None:
            stop = getattr(_service_instance, "stop", None)
            if callable(stop):
                await stop()
    finally:
        _service_instance = None
        try:
            delattr(app.state, "agent_repository")  # type: ignore[attr-defined]
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _start(app)
    try:
        yield
    finally:
        await _stop(app)


app = FastAPI(title="Agentic PKM API (lifespan+routers)", lifespan=lifespan)
app.include_router(agent_router)
app.include_router(interesting_router)
app.include_router(dashboard_router)


__all__ = ["app"]
