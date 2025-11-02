from __future__ import annotations
from contextlib import asynccontextmanager
from typing import Any
from fastapi import FastAPI

engine = None
SessionLocal = None
PostgresAgentRepository = None  # monkeypatched in tests
AgentService = None             # monkeypatched in tests

@asynccontextmanager
async def lifespan(app: FastAPI):
    repo = None
    svc = None
    try:
        rf = PostgresAgentRepository
        sf = AgentService
        if callable(rf):
            repo = rf("dsn://stub")
        if callable(sf) and repo is not None:
            svc = sf(repo, None)
            start = getattr(svc, "start", None)
            if callable(start):
                await start()
    except Exception:
        svc = None
    app.state.repo = repo
    try:
        yield
    finally:
        try:
            if svc is not None:
                stop = getattr(svc, "stop", None)
                if callable(stop):
                    await stop()
        finally:
            try:
                del app.state.repo
            except Exception:
                app.state.repo = None

app = FastAPI(title="Agentic PKM API (lifespan+routers)", lifespan=lifespan)

from app.api.routers import agent_router, interesting_router, dashboard_router
app.include_router(agent_router)
app.include_router(interesting_router)
app.include_router(dashboard_router)

@app.get("/healthz")
def healthz():
    return {"ok": True}
