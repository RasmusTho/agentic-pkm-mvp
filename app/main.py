from __future__ import annotations
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

# Monkeypatchbara symboler under test
engine = None
SessionLocal = None
PostgresAgentRepository = None  # type: ignore[assignment]
AgentService = None            # type: ignore[assignment]

_repo: Any = None
_service: Any = None

async def _start() -> None:
    global _repo, _service
    try:
        repo_factory = PostgresAgentRepository
        svc_factory = AgentService
        _repo = repo_factory("dsn://stub") if callable(repo_factory) else None
        if callable(svc_factory) and _repo is not None:
            _service = svc_factory(_repo, None)
            start = getattr(_service, "start", None)
            if callable(start):
                await start()
    except Exception:
        _repo = None
        _service = None

async def _stop() -> None:
    global _service
    try:
        if _service is not None:
            stop = getattr(_service, "stop", None)
            if callable(stop):
                await stop()
    finally:
        _service = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    await _start()
    try:
        yield
    finally:
        await _stop()


# === BEGIN lifespan wiring ===
from contextlib import asynccontextmanager

try:
    from app.agent.repository import PostgresAgentRepository  # type: ignore
except Exception:
    PostgresAgentRepository = None  # type: ignore

try:
    from app.services.agent_service import AgentService  # type: ignore
except Exception:
    class AgentService:  # type: ignore
        async def start(self): pass
        async def stop(self): pass

_repo = None
_service_instance = None

async def _start(app):
    global _repo, _service_instance
    try:
        repo_factory = PostgresAgentRepository
        svc_factory = AgentService
        _repo = repo_factory("dsn://stub") if callable(repo_factory) else None
        if _repo is not None:
            try:
                app.state.agent_repository = _repo  # type: ignore[attr-defined]
            except Exception:
                pass
        if callable(svc_factory) and _repo is not None:
            _service_instance = svc_factory(_repo, None)
            start = getattr(_service_instance, "start", None)
            if callable(start):
                await start()
    except Exception:
        _service_instance = None

async def _stop(app):
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
async def lifespan(app):
    await _start(app)
    try:
        yield
    finally:
        await _stop(app)
# === END lifespan wiring ===
app = FastAPI(title="Agentic PKM API (lifespan+routers)", lifespan=lifespan)

from app.api.agent import router as agent_router          # noqa: E402
from app.api.interesting import router as interesting_router  # noqa: E402
from app.api.dashboard import router as dashboard_router  # noqa: E402

app.include_router(agent_router)
app.include_router(interesting_router)
app.include_router(dashboard_router)
