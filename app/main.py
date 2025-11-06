from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Callable, Optional

from fastapi import FastAPI

# Monkeypatchable placeholders (CI smoke patches these to fakes)
engine = None
SessionLocal = None
PostgresAgentRepository: Optional[Callable[..., Any]] = None  # patched in tests
AgentService: Optional[Callable[..., Any]] = None             # patched in tests


async def _start(app: FastAPI) -> None:
    """
    Lifespan start: instantiate repository via PostgresAgentRepository (if callable),
    then create AgentService(repo, config_manager=None) and await start().
    Attach both to app.state so deps/routers can reach them.
    """
    repo = None
    svc = None
    try:
        if callable(PostgresAgentRepository):
            # DSN is irrelevant under tests; fakes ignore it.
            repo = PostgresAgentRepository("dsn://stub")  # type: ignore[misc]
        if callable(AgentService) and repo is not None:
            svc = AgentService(repo, None)  # type: ignore[misc]
            start = getattr(svc, "start", None)
            if callable(start):
                await start()
    finally:
        # Make discoverable to dependencies/routers
        app.state.agent_repository = repo
        app.state.agent_service = svc


async def _stop(app: FastAPI) -> None:
    """
    Lifespan stop: if a service exists and exposes stop(), await it and clear state.
    """
    try:
        svc = getattr(app.state, "agent_service", None)
        if svc is not None:
            stop = getattr(svc, "stop", None)
            if callable(stop):
                await stop()
    finally:
        # Ensure clean state for subsequent TestClient runs
        if hasattr(app.state, "agent_repository"):
            delattr(app.state, "agent_repository")
        if hasattr(app.state, "agent_service"):
            delattr(app.state, "agent_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _start(app)
    try:
        yield
    finally:
        await _stop(app)


app = FastAPI(title="Agentic PKM API (lifespan+routers)", lifespan=lifespan)

# Routers expect get_agent_repository() to find app.state.agent_repository
from app.api.agent import router as agent_router  # noqa: E402
from app.api.interesting import router as interesting_router  # noqa: E402
from app.api.dashboard import router as dashboard_router  # noqa: E402

app.include_router(agent_router)
app.include_router(interesting_router)
app.include_router(dashboard_router)
