"""
TEST SHIM for tests/test_agent_smoke.py

- Exposes /agent/health, /interesting, /dashboard as minimal routes.
- Designed to be monkeypatched with PostgresAgentRepository/AgentService in tests.
- Not production wiring; replace with real lifespan + routers later.
"""
from typing import Any, Iterable
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Agentic PKM API (shim)")

# Platshållare som testsviten monkeypatchar
engine = None
SessionLocal = None
PostgresAgentRepository = None
AgentService = None
InterestingService = None
ConfigManager = type("ConfigManager", (), {})

_service_instance: Any = None
_repo: Any = None

def _collect_interesting(repo: Any) -> list[dict]:
    try:
        items = getattr(repo, "interesting_items", None)
        if isinstance(items, dict):
            return list(items.values())
        if isinstance(items, Iterable):
            return list(items)
    except Exception:
        pass
    return []

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/agent/health")
def agent_health():
    repo = _repo
    hb = None
    if repo is not None:
        for name in ("get_last_heartbeat", "last_heartbeat"):
            f = getattr(repo, name, None)
            if callable(f):
                try:
                    hb = f()
                    break
                except Exception:
                    pass
        if hb is None:
            data = getattr(repo, "heartbeats", None) or getattr(repo, "_heartbeats", None)
            if isinstance(data, dict) and data:
                hb = data.get("background-agent") or list(data.values())[-1]
            elif isinstance(data, list) and data:
                hb = data[-1]
    if not isinstance(hb, dict):
        hb = {"status": "unknown"}
    return {"ok": True, "heartbeat": hb}

@app.get("/agent/interesting")
def agent_interesting():
    return {"items": _collect_interesting(_repo)}

@app.get("/interesting")
def interesting_alias():
    return {"items": _collect_interesting(_repo)}

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_alias():
    items = _collect_interesting(_repo)
    def item_title(it: dict) -> str:
        payload = it.get("payload") or {}
        return str(payload.get("title") or it.get("object_id"))
    lis = "".join(
        f"<li><strong>{item_title(it)}</strong>"
        f" <small>(score={it.get('score','')})</small></li>"
        for it in items
    )
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Dashboard</title></head>
<body>
  <h1>Interesting Items</h1>
  <ul>{lis or "<li><em>No items</em></li>"}</ul>
</body></html>"""
    return html

# Inkludera ev. riktiga routrar om de finns
try:
    from app.api.interesting import router as interesting_router
    app.include_router(interesting_router, prefix="/api")
except Exception:
    pass

@app.on_event("startup")
async def _startup():
    global _service_instance, _repo
    try:
        _repo = PostgresAgentRepository("dsn") if callable(PostgresAgentRepository) else None
        cfg = ConfigManager() if callable(getattr(ConfigManager, "__call__", None)) else ConfigManager
        svc_factory = AgentService if callable(AgentService) else (InterestingService if callable(InterestingService) else None)
        if svc_factory is not None:
            _service_instance = svc_factory(_repo, cfg)
            start = getattr(_service_instance, "start", None)
            if start:
                await start()
    except Exception:
        _service_instance = None

@app.on_event("shutdown")
async def _shutdown():
    global _service_instance
    try:
        if _service_instance is not None:
            stop = getattr(_service_instance, "stop", None)
            if stop:
                await stop()
    finally:
        _service_instance = None
