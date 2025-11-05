from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI

# Shim-attribut som tests/agent_smoke monkeypatchar
engine = None
SessionLocal = None
PostgresAgentRepository = None  # patched in tests
AgentService = None             # patched in tests

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="Agentic PKM API", lifespan=lifespan)

from app.api.agent import router as agent_router
from app.api.interesting import router as interesting_router
from app.api.dashboard import router as dashboard_router

app.include_router(agent_router)
app.include_router(interesting_router)
app.include_router(dashboard_router)

@app.get("/healthz")
def healthz():
    return {"ok": True}
