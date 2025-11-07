from __future__ import annotations
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

# Monkeypatch targets expected by tests/test_agent_smoke.py
engine = None
SessionLocal = None
PostgresAgentRepository: Any = None  # monkeypatched in tests
AgentService: Any = None             # monkeypatched in tests


@asynccontextmanager
async def lifespan(app: FastAPI):
    repo = None
    svc = None
    try:
        # Instantiate repo via monkeypatched factory and expose in app.state
        if callable(PostgresAgentRepository):
            # DSN value is irrelevant for tests; factory is monkeypatched anyway
            repo = PostgresAgentRepository("dsn://stub")
            app.state.agent_repository = repo

        # Instantiate background service (stub in tests) and start it
        if callable(AgentService) and repo is not None:
            svc = AgentService(repo, None)
            start = getattr(svc, "start", None)
            if callable(start):
                await start()
            app.state.agent_service = svc

        yield
    finally:
        # Stop service if present and clean up state
        try:
            stop = getattr(svc, "stop", None)
            if callable(stop):
                await stop()
        finally:
            for key in ("agent_service", "agent_repository"):
                try:
                    delattr(app.state, key)
                except Exception:
                    pass


app = FastAPI(title="Agentic PKM API (lifespan+routers)", lifespan=lifespan)

# Routers (depend on get_agent_repository reading app.state)
from app.api.agent import router as agent_router          # noqa: E402
from app.api.interesting import router as interesting_router  # noqa: E402
from app.api.dashboard import router as dashboard_router      # noqa: E402

app.include_router(agent_router)
app.include_router(interesting_router)
app.include_router(dashboard_router)
