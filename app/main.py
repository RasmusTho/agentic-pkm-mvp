import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

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

from app.api.items import router as items_router
from app.auth import configure_rate_limit_storage, limiter
from app.db import Base, engine
from app.deps import get_db
from app.health import HealthSummary, health_summary
from app.observability import configure_metrics, setup_logging
from app.settings import settings

from .context_loader import load_context


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    yield


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "Rate limit exceeded"},
    )


setup_logging()
configure_rate_limit_storage()
app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
app.add_middleware(SlowAPIMiddleware)
configure_metrics(app)
app.include_router(items_router)


@app.get("/")
def root() -> dict[str, bool | str]:
    return {"ok": True, "service": "api"}


@app.get("/health")
def health(db: Session = Depends(get_db)) -> HealthSummary:
    summary = health_summary(db)
    if summary["status"] != "ok":
        raise HTTPException(status_code=503, detail=summary)
    return summary


@app.get("/version")
def version() -> dict[str, str]:
    return {"version": settings.app_version}


@app.get("/context")
def get_context() -> dict[str, Any]:
    return load_context()
