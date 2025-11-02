"""
TEST SHIM for tests/test_agent_smoke.py (lifespan version)

- Minimal FastAPI-app med /agent/health, /interesting, /dashboard (HTML).
- Designad för monkeypatch i test: PostgresAgentRepository och AgentService.
- Inte produktionskoppling — ersätt med riktig wiring/routers senare.
"""
from __future__ import annotations
from contextlib import asynccontextmanager
from typing import Any, Iterable

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

# Monkeypatchbara platshållare (måste finnas som attribut)
engine = None
SessionLocal = None
PostgresAgentRepository = None  # type: ignore[assignment]
AgentService = None  # type: ignore[assignment]

_repo: Any = None
_service_instance: Any = None


def _latest_heartbeat(repo: Any) -> dict[str, Any] | None:
    try:
        for name in ("last_heartbeat", "get_last_heartbeat", "latest_heartbeat"):
            fn = getattr(repo, name, None)
            if callable(fn):
                return fn()
        hb = getattr(repo, "heartbeats", None)
        if hb is None:
            return None
        data = hb() if callable(hb) else hb
        items: list[dict[str, Any]] = []
        if isinstance(data, dict):
            items = list(data.values())
        elif isinstance(data, Iterable):
            items = list(data)  # type: ignore[arg-type]
        if not items:
            return None
        try:
            items.sort(key=lambda x: x.get("created_at"), reverse=True)
        except Exception:
            pass
        return items[0]
    except Exception:
        return None


def _interesting_items(repo: Any) -> list[dict[str, Any]]:
    try:
        items = getattr(repo, "interesting_items", None)
        if items is None:
            return []
        items = items() if callable(items) else items
        if isinstance(items, dict):
            return list(items.values())
        if isinstance(items, Iterable):
            return list(items)  # type: ignore[return-value]
        return []
    except Exception:
        return []


async def _start() -> None:
    global _repo, _service_instance
    try:
        repo_factory = PostgresAgentRepository
        svc_factory = AgentService
        if callable(repo_factory):
            _repo = repo_factory("dsn://stub")
        else:
            _repo = None
        if callable(svc_factory) and _repo is not None:
            _service_instance = svc_factory(_repo, None)
            start = getattr(_service_instance, "start", None)
            if callable(start):
                await start()
    except Exception:
        _service_instance = None


async def _stop() -> None:
    global _service_instance
    try:
        if _service_instance is not None:
            stop = getattr(_service_instance, "stop", None)
            if callable(stop):
                await stop()
    finally:
        _service_instance = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _start()
    try:
        yield
    finally:
        await _stop()


app = FastAPI(title="Agentic PKM API (shim, lifespan)", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/agent/health")
def agent_health():
    hb = _latest_heartbeat(_repo) if _repo is not None else None
    return {"ok": True, "heartbeat": hb or {"status": "unknown"}}


@app.get("/interesting")
def list_interesting():
    items = _interesting_items(_repo) if _repo is not None else []
    return {"items": items, "ok": True}


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    data = list_interesting()
    rows = []
    for item in data["items"]:
        title = (item.get("payload") or {}).get("title") or str(item.get("object_id", ""))  # type: ignore[index]
        score = item.get("score")  # type: ignore[index]
        rows.append(f"<li>{title} — score {score}</li>")
    body = f"<h1>Interesting Items</h1><ul>{''.join(rows) or '<li>None</li>'}</ul>"
    return HTMLResponse(f"<!doctype html><html><body>{body}</body></html>")
