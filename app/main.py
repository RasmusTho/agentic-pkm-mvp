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

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from app.api.items import router as items_router
from app.db import Base, engine
from app.deps import get_db
from app.health import HealthSummary, health_summary
from app.settings import settings

from .context_loader import load_context


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(lifespan=lifespan)
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
