import os
from contextlib import asynccontextmanager

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

from app.db import Base, engine
from app.deps import get_db
from app.api.items import router as items_router
from app.health import health_summary
from app.settings import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(items_router)

@app.get("/")
def root():
    return {"ok": True, "service": "api"}

from .context_loader import load_context


@app.get("/health")
def health(db: Session = Depends(get_db)):
    summary = health_summary(db)
    if summary["status"] != "ok":
        raise HTTPException(status_code=503, detail=summary)
    return summary


@app.get("/version")
def version():
    return {"version": settings.app_version}

@app.get("/context")
def get_context():
    return load_context()
