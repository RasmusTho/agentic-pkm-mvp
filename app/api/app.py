from fastapi import FastAPI
from app.middleware.trace import TraceIdMiddleware

try:
    from app.api.routes.ingest import router as ingest_router
except ImportError:
    ingest_router = None

try:
    from app.api.routes.search import router as search_router
except ImportError:
    search_router = None

app = FastAPI(title="Agentic PKM API")
app.add_middleware(TraceIdMiddleware)

if ingest_router is not None:
    app.include_router(ingest_router)
if search_router is not None:
    app.include_router(search_router)
