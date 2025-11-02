import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from pathlib import Path

if os.getenv("DEBUGPY") == "1":
    import debugpy

    port = int(os.getenv("DEBUGPY_PORT", "5678"))
    debugpy.listen(("0.0.0.0", port))
    print(f"debugpy listening on 0.0.0.0:{port}")
    if os.getenv("DEBUGPY_WAIT") == "1":
        print("Waiting for debugger attach...")
        debugpy.wait_for_client()

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy.orm import Session

from app.agent.repository import PostgresAgentRepository
from app.agent.service import AgentService
from app.api.agent import router as agent_router
from app.api.ingest import router as ingest_router
from app.api.items import router as items_router
from app.api.interesting import router as interesting_router
from app.api.search import router as search_router
from app.api.ui import router as ui_router
from app.auth import configure_rate_limit_storage, limiter
from app.config.agent import AgentConfigManager
from app.db import Base, engine
from app.deps import get_agent_repository, get_db
from app.health import HealthSummary, health_summary
from app.observability import configure_metrics, setup_logging
from app.settings import settings

from .context_loader import load_context


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    repo = PostgresAgentRepository(settings.psycopg_dsn)
    config_manager = AgentConfigManager(Path(settings.agent_config_path))
    service = AgentService(repo, config_manager)
    app.state.agent_repository = repo  # type: ignore[attr-defined]
    app.state.agent_config_manager = config_manager  # type: ignore[attr-defined]
    app.state.agent_service = service  # type: ignore[attr-defined]
    await service.start()
    yield
    await service.stop()
    config_manager.stop()
    repo.close()


def _rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, RateLimitExceeded):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Rate limit exceeded"},
        )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": str(exc)}
    )


setup_logging()
configure_rate_limit_storage()
app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
app.add_middleware(SlowAPIMiddleware)
configure_metrics(app)
app.include_router(items_router)
app.include_router(ingest_router)
app.include_router(search_router)
app.include_router(agent_router)
app.include_router(interesting_router)
app.include_router(ui_router)


@app.get("/")
def root() -> dict[str, bool | str]:
    return {"ok": True, "service": "api"}


@app.get("/health")
def health(
    db: Session = Depends(get_db),
    agent_repo=Depends(get_agent_repository),
) -> HealthSummary:
    summary = health_summary(db, agent_repo)
    if summary["status"] != "ok":
        raise HTTPException(status_code=503, detail=summary)
    return summary


@app.get("/version")
def version() -> dict[str, str]:
    return {"version": settings.app_version}


@app.get("/context")
def get_context() -> dict[str, Any]:
    return load_context()
