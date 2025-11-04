"""FastAPI lifespan shim used by smoke tests."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app.api.routers import agent_router, dashboard_router, interesting_router

# Monkeypatched in tests to supply real implementations.
engine = None
SessionLocal = None
PostgresAgentRepository = None  # type: ignore[assignment]
AgentService = None  # type: ignore[assignment]

_repo: Any = None
_service_instance: Any = None


async def _start(app: FastAPI) -> None:
    """Instantiate the repository/service shims and attach them to app state."""
    global _repo, _service_instance
    repo = None
    svc = None
    try:
        repo_factory = PostgresAgentRepository
        if callable(repo_factory):
            repo = repo_factory("dsn://stub")
    except Exception:
        repo = None
    try:
        svc_factory = AgentService
        if callable(svc_factory) and repo is not None:
            svc = svc_factory(repo, None)
            start = getattr(svc, "start", None)
            if callable(start):
                await start()
    except Exception:
        svc = None
    _repo = repo
    _service_instance = svc
    try:
        app.state.repo = repo
    except Exception:
        pass


async def _stop(app: FastAPI) -> None:
    """Stop the service shim and clear app state."""
    global _repo, _service_instance
    try:
        if _service_instance is not None:
            stop = getattr(_service_instance, "stop", None)
            if callable(stop):
                await stop()
    finally:
        _service_instance = None
        _repo = None
    try:
        del app.state.repo
    except Exception:
        try:
            app.state.repo = None
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


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}
