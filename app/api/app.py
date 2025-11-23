from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.middleware.trace import TraceIdMiddleware
from app.observability import configure_metrics

try:
    from app.api.routes.ingest import router as ingest_router
except ImportError:
    ingest_router = None

try:
    from app.api.routes.search import router as search_router
except ImportError:
    search_router = None

try:
    from app.api.routes.status import router as status_router
except ImportError:
    status_router = None

try:
    from app.api.routes.ask import router as ask_router
except ImportError:
    ask_router = None

static_dir = Path(__file__).resolve().parent.parent / "web" / "static"

app = FastAPI(title="Agentic PKM API")
app.add_middleware(TraceIdMiddleware)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
configure_metrics(app)

if ingest_router is not None:
    app.include_router(ingest_router)
if search_router is not None:
    app.include_router(search_router)
if status_router is not None:
    app.include_router(status_router, prefix="/api")
if ask_router is not None:
    app.include_router(ask_router, prefix="/api")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Interim dashboard for status visibility and manual ASK checks."""
    index_path = static_dir / "index.html"
    return HTMLResponse(index_path.read_text(encoding="utf-8"))
