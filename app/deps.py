from __future__ import annotations
from typing import Any, Optional, Iterator
from fastapi import Request

# Minimal dummy som uppfyller routrarnas förväntade interface
class _DummyAgentRepository:
    def get_last_heartbeat(self) -> dict[str, Any] | None:
        return {"status": "unknown"}
    def fetch_top_interesting(self, limit: int = 20) -> list[dict[str, Any]]:
        return []
    def interesting_summary(self) -> dict[str, Any]:
        return {"items": 0}

def _repo_from_request(request: Optional[Request]) -> Any | None:
    try:
        return getattr(getattr(request, "app", None).state, "agent_repository", None)
    except Exception:
        return None

def _repo_from_main() -> Any | None:
    try:
        from app import main as main_module  # late import to avoid cycles
        return getattr(getattr(main_module, "app", None).state, "agent_repository", None)
    except Exception:
        return None

def get_agent_repository(request: Optional[Request] = None) -> Any:
    """
    FastAPI dependency: returnera agent-repository om det finns i app.state,
    annars en dummy som inte kraschar i smoke.
    """
    repo = _repo_from_request(request) or _repo_from_main()
    return repo or _DummyAgentRepository()

def get_db() -> Iterator[Any]:
    """
    FastAPI dependency: yield en DB-session om main.SessionLocal finns.
    I smoke/CI-läge yield:ar vi None (ingen hård PG-koppling).
    """
    try:
        from app import main as main_module  # late import
        SessionLocal = getattr(main_module, "SessionLocal", None)
        if SessionLocal is None:
            yield None
            return
        db = SessionLocal()
        try:
            yield db
        finally:
            close = getattr(db, "close", None)
            if callable(close):
                close()
    except Exception:
        # Säkert fallback-beteende i smoke
        yield None
